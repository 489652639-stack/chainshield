"""ChainShield: read-only multi-chain risk screening, standard library only.

Missing evidence is *unknown*, never a clean bill of health.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
import time
import runtime_policy
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

EVM_PATTERN = re.compile(r"0x[a-fA-F0-9]{40}\Z")
SOL_PATTERN = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}\Z")
CHAINS = {"bnb": "56", "eth": "1", "sol": "sol"}


class DataError(Exception):
    pass


def normalize_address(chain: str, address: str) -> str:
    if chain not in CHAINS:
        raise ValueError("暂不支持这条链")
    if not isinstance(address, str):
        raise ValueError("请输入合约地址")
    address = address.strip()
    if chain in ("bnb", "eth"):
        if not EVM_PATTERN.fullmatch(address):
            raise ValueError("BNB / ETH 合约地址应为 0x 开头的 42 位十六进制地址")
        return address.lower()
    if not SOL_PATTERN.fullmatch(address):
        raise ValueError("索拉纳铸币地址格式不正确（通常为 32–44 位地址字符）")
    # Solana public keys decode to exactly 32 bytes (not just base58-looking text).
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = 0
    for char in address:
        n = n * 58 + alphabet.index(char)
    leading_zeroes = len(address) - len(address.lstrip("1"))
    decoded_len = (n.bit_length() + 7) // 8 + leading_zeroes
    if decoded_len != 32:
        raise ValueError("索拉纳铸币地址必须能解码为 32 字节公钥")
    return address


def get_json(url: str, headers: dict | None = None) -> dict:
    host = urllib.parse.urlparse(url).hostname or '未知接口'
    try: runtime_policy.before_request(host)
    except ValueError as exc: raise DataError(str(exc)) from exc
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ChainShield/1.6", **(headers or {})})
    attempts = 1 if host == "api.rugcheck.xyz" else 2
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=9) as resp:
                if resp.status != 200: raise DataError(f"接口返回异常状态（状态码 {resp.status}）")
                data = resp.read(2_000_001)
                if len(data) > 2_000_000: raise DataError("返回数据过大")
                result = json.loads(data)
                if not isinstance(result, dict): raise DataError("接口数据格式不正确")
                runtime_policy.record(host, True)
                return result
        except urllib.error.HTTPError as exc:
            if exc.code in (500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(0.25)
                continue
            runtime_policy.record(host, False)
            message = "接口请求过于频繁，请稍后重试" if exc.code == 429 else "接口授权暂不可用" if exc.code in (401, 403) else "接口返回异常状态"
            raise DataError(f"{message}（状态码 {exc.code}）") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt + 1 < attempts:
                time.sleep(0.25)
                continue
            runtime_policy.record(host, False)
            raise DataError("自动重试后仍无法连接，请检查网络或稍后重试") from exc
        except (ValueError, UnicodeError) as exc:
            runtime_policy.record(host, False)
            raise DataError("接口响应无法解析") from exc
        except DataError:
            runtime_policy.record(host, False)
            raise


def goplus(chain: str, address: str) -> dict:
    try: runtime_policy.enabled("GoPlus")
    except ValueError as exc: raise DataError(str(exc)) from exc
    if chain == "sol":
        path = runtime_policy.path("goplus_sol")
    else:
        path = runtime_policy.path("goplus_evm", chain=CHAINS[chain])
    url = "https://api.gopluslabs.io" + path + "?" + urllib.parse.urlencode({"contract_addresses": address})
    headers = {}
    key = os.getenv("GOPLUS_ACCESS_TOKEN", "").strip()
    if key:
        headers["Authorization"] = "Bearer " + key.removeprefix("Bearer ")
    result = get_json(url, headers)
    if str(result.get("code")) != "1":
        raise DataError("服务未返回有效结果（可能需要授权或已限流）")
    body = result.get("result")
    if not isinstance(body, dict):
        raise DataError("没有找到安全信息")
    # Solana and EVM response structures use an address-keyed result map.
    token = body.get(address)
    if chain != "sol" and not isinstance(token, dict):
        token = next((v for k, v in body.items() if isinstance(v, dict) and k.lower() == address.lower()), None)
    if not isinstance(token, dict) or not token:
        raise DataError("该代币尚无可用检测记录")
    return runtime_policy.adapt("sol" if chain == "sol" else "evm", token)


def honeypot(chain: str, address: str) -> dict:
    try: runtime_policy.enabled("Honeypot.is")
    except ValueError as exc: raise DataError(str(exc)) from exc
    url = "https://api.honeypot.is" + runtime_policy.path("honeypot") + "?" + urllib.parse.urlencode({"address": address, "chainID": CHAINS[chain]})
    headers = {}
    if os.getenv("HONEYPOT_API_KEY"):
        headers["X-API-KEY"] = os.environ["HONEYPOT_API_KEY"].strip()
    response = runtime_policy.adapt("honeypot", get_json(url, headers))
    summary = as_dict(response.get("summary"))
    if not (summary.get("risk") in ("unknown", "very_low", "low", "medium", "high", "very_high", "honeypot") or
            isinstance(as_dict(response.get("honeypotResult")).get("isHoneypot"), bool) or
            isinstance(response.get("simulationSuccess"), bool)):
        raise DataError("Honeypot.is 没有返回有效的检测数据")
    returned_address = as_dict(response.get("token")).get("address")
    returned_chain = as_dict(response.get("chain")).get("id")
    pair_chain = as_dict(response.get("pair")).get("chainId")
    if returned_address is not None and str(returned_address).lower() != address.lower():
        raise DataError("Honeypot.is 返回的代币地址不匹配")
    if any(value is not None and str(value) != CHAINS[chain] for value in (returned_chain, pair_chain)):
        raise DataError("Honeypot.is 返回的区块链不匹配")
    return response


def rugcheck(_chain: str, address: str) -> dict:
    quoted = urllib.parse.quote(address, safe="")
    try: runtime_policy.enabled("RugCheck")
    except ValueError as exc: raise DataError(str(exc)) from exc
    base = "https://api.rugcheck.xyz" + runtime_policy.path("rugcheck", address=quoted)
    token = os.getenv("RUGCHECK_API_KEY", "").strip()
    headers = {"Authorization": "Bearer " + token.removeprefix("Bearer ")} if token else {}
    def validate_report(report: dict) -> dict:
        # HTTP 200 with an error/message body is NOT a successful screening.
        if "mint" in report and report["mint"] != address:
            raise DataError("RugCheck 返回的铸币地址不匹配")
        if not (isinstance(report.get("risks"), list) or
                any(key in as_dict(report.get("token")) for key in ("mintAuthority", "freezeAuthority")) or
                num(report.get("score")) is not None or num(report.get("score_normalised")) is not None):
            raise DataError("RugCheck 没有返回有效风险报告")
        return runtime_policy.adapt("rugcheck", report)
    try:
        return validate_report(get_json(base, headers))
    except DataError as full_error:
        try:
            summary = validate_report(get_json(base + "/summary", headers))
            summary["_summary_only"] = True
            return summary
        except DataError:
            raise full_error


def as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def flag(value: Any) -> bool | None:
    if isinstance(value, dict):
        value = value.get("status")
    if value in (True, "1", 1, "true", "True"):
        return True
    if value in (False, "0", 0, "false", "False"):
        return False
    return None


def first_known(*values: Any) -> bool | None:
    known = [flag(v) for v in values]
    if True in known:
        return True
    if known and False in known:
        return False
    return None


def num(value: Any) -> float | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (ValueError, TypeError, OverflowError):
        return None


def check(id: str, group: str, title: str, state: str, detail: str, source: str) -> dict:
    return {"id": id, "group": group, "title": title, "state": state, "detail": detail, "source": source}


def boolean_check(id: str, group: str, title: str, val: bool | None, danger: str, clean: str, source: str, severity="high") -> dict:
    state = severity if val is True else ("ok" if val is False else "unknown")
    return check(id, group, title, state, danger if val is True else (clean if val is False else "未取得可验证信息"), source)


def percent_tax(value: Any, fraction: bool) -> float | None:
    x = num(value)
    return x * (100 if fraction else 1) if x is not None and x >= 0 else None


def tax_check(id: str, title: str, go_val: Any, honey_val: Any, has_go: bool, has_honey: bool) -> dict:
    go_pct = percent_tax(go_val, True) if has_go else None
    hp_pct = percent_tax(honey_val, False) if has_honey else None
    parts = []
    if go_pct is not None:
        parts.append(f"GoPlus {go_pct:g}%")
    if hp_pct is not None:
        parts.append(f"Honeypot.is {hp_pct:g}%")
    if not parts:
        return check(id, "交易风险", title, "unknown", "尚无可验证税率（未开池时很常见）", "GoPlus / Honeypot.is")
    high = max(v for v in (go_pct, hp_pct) if v is not None)
    state = "high" if high >= 50 else "warn" if high >= 10 else "ok" if high == 0 else "warn"
    return check(id, "交易风险", title, state, "当前查询：" + "；".join(parts) + "。税率可能随时变化。", "GoPlus / Honeypot.is")


def normalize_evm(go: dict | None, hp: dict | None) -> tuple[list[dict], dict]:
    g, h = as_dict(go), as_dict(hp)
    present_g, present_h = go is not None, hp is not None
    out: list[dict] = []
    push = out.append
    hres, hsim, hcode, hsummary = (as_dict(h.get(k)) for k in ("honeypotResult", "simulationResult", "contractCode", "summary"))
    # Failed/incomplete simulations cannot supply a verified zero tax.
    if h.get("simulationSuccess") is not True:
        hsim = {}
    b20 = as_dict(as_dict(g.get("b20_token")).get("b20_info"))
    b20_flag = lambda key: as_dict(b20.get(key)).get("status")

    hp_honey = flag(hres.get("isHoneypot"))
    go_honey = flag(g.get("is_honeypot"))
    honey_state = first_known(hp_honey, go_honey, True if hsummary.get("risk") == "honeypot" else None)
    push(boolean_check("honeypot", "交易风险", "蜜罐 / 无法卖出", honey_state,
        "至少一家检测提供商识别出蜜罐风险，可能买入后无法卖出", "目前检测未识别蜜罐；不保证之后仍能卖出", "GoPlus / Honeypot.is"))

    sell_all = flag(g.get("cannot_sell_all"))
    sell_b20 = flag(b20_flag("cannot_sell"))
    push(boolean_check("sell_restricted", "交易风险", "卖出限制", first_known(sell_all, sell_b20),
        "检测到限制卖出或无法一次全部卖出的机制", "未发现已覆盖的卖出限制机制", "GoPlus", "warn" if sell_all is True and sell_b20 is not True else "high"))

    push(boolean_check("cannot_buy", "交易风险", "限制买入", first_known(g.get("cannot_buy"), b20_flag("cannot_buy")),
        "合约可能限制普通用户买入，模拟结果可能受到反机器人规则影响", "未识别到限制买入机制", "GoPlus", "warn"))
    push(tax_check("buy_tax", "买入税", g.get("buy_tax"), hsim.get("buyTax"), present_g, present_h))
    push(tax_check("sell_tax", "卖出税", g.get("sell_tax"), hsim.get("sellTax"), present_g, present_h))

    push(boolean_check("mutable_tax", "权限风险", "管理员可修改交易税", first_known(g.get("slippage_modifiable"), g.get("personal_slippage_modifiable")),
        "税率可修改，未来可能突然提高卖出税或针对特定地址收税", "未识别到可修改交易税的权限", "GoPlus"))
    push(boolean_check("blacklist", "权限风险", "黑名单机制", first_known(g.get("is_blacklisted"), b20_flag("blacklist")),
        "合约可限制指定地址交易", "未识别到黑名单机制", "GoPlus"))
    push(boolean_check("whitelist", "权限风险", "白名单限制", first_known(g.get("is_whitelisted"), b20_flag("whitelist")),
        "存在白名单功能，未列入名单的用户可能受限", "未识别到白名单限制", "GoPlus", "warn"))
    push(boolean_check("pausable", "权限风险", "暂停交易权限", first_known(g.get("transfer_pausable"), b20_flag("transfer_pausable")),
        "存在暂停转账/交易的功能", "未识别到暂停交易功能", "GoPlus"))
    push(boolean_check("proxy", "权限风险", "代理 / 可升级调用", first_known(g.get("is_proxy"), hcode.get("isProxy")),
        "识别到代理合约，需进一步确认升级管理员和实现合约", "未识别到根合约代理模式", "GoPlus / Honeypot.is", "warn"))
    push(boolean_check("delegatecall", "权限风险", "调用链存在代理调用", flag(hcode.get("hasProxyCalls")),
        "交易调用链出现 delegatecall，可能涉及外部实现合约；需人工核对", "本次调用链未识别到 delegatecall", "Honeypot.is", "warn"))
    owner = str(g.get("owner_address") or "").strip()
    if owner and owner.lower() not in ("0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead"):
        owner_state, owner_detail = "warn", "GoPlus 返回管理员地址：" + owner[:42] + "。具体可操作权限须结合下列检测结果"
    elif owner.lower() in ("0x0000000000000000000000000000000000000000", "0x000000000000000000000000000000000000dead") or ("owner_address" in g and g["owner_address"] == ""):
        owner_state, owner_detail = "ok", "GoPlus 明确报告无管理员或管理员为销毁地址；仍需排查隐藏权限与回收所有权"
    else:
        owner_state, owner_detail = "unknown", "无法确认当前管理员及其可修改的合约条件"
    push(check("owner", "权限风险", "管理员控制权", owner_state, owner_detail, "GoPlus"))
    push(boolean_check("hidden_owner", "权限风险", "隐藏管理员", flag(g.get("hidden_owner")),
        "GoPlus 发现隐藏管理员权限，表面放弃所有权不代表真正放弃", "未识别到隐藏管理员", "GoPlus"))
    push(boolean_check("recover_owner", "权限风险", "管理员可重新取得所有权", flag(g.get("can_take_back_ownership")),
        "存在重新取得所有权的能力；即使当前地址是空地址也可能恢复控制", "未识别到所有权回收机制", "GoPlus"))
    push(boolean_check("selfdestruct", "权限风险", "合约自毁能力", flag(g.get("selfdestruct")),
        "合约可能执行自毁或停用逻辑；实际效果依链上协议版本和部署方式变化", "未识别到自毁能力", "GoPlus", "warn"))
    push(boolean_check("external_call", "权限风险", "合约外部调用", flag(g.get("external_call")),
        "合约能够调用外部合约，交易结果可能依赖其他代码", "未识别到外部调用功能", "GoPlus", "warn"))
    push(boolean_check("gas_abuse", "交易风险", "异常 Gas 消耗", flag(g.get("gas_abuse")),
        "检测服务报告可疑 Gas 费用行为", "未识别到异常 Gas 费用行为", "GoPlus"))
    push(boolean_check("mintable", "权限风险", "增发代币能力", first_known(g.get("is_mintable"), b20_flag("mintable")),
        "检测到可能增发代币的能力", "未识别到增发权限", "GoPlus", "warn"))
    push(boolean_check("balance_control", "权限风险", "管理员修改余额", first_known(g.get("owner_change_balance"), b20_flag("owner_change_balance")),
        "管理员可能直接修改用户代币余额", "未识别到管理员直接修改余额", "GoPlus"))
    push(boolean_check("antiwhale", "交易风险", "交易额 / 持仓限制", first_known(g.get("is_anti_whale"), g.get("anti_whale_modifiable")),
        "合约存在交易额或持仓上限，可能影响卖出", "未识别到交易额/持仓上限", "GoPlus", "warn"))
    push(boolean_check("cooldown", "交易风险", "交易冷却时间", flag(g.get("trading_cooldown")),
        "存在交易冷却时间，短时交易可能失败", "未识别到交易冷却时间", "GoPlus", "warn"))

    source_values = [flag(g.get("is_open_source")), flag(hcode.get("rootOpenSource"))]
    # A source that flags missing source code must not be overridden by another saying yes.
    source_status = False if False in source_values else (True if True in source_values else None)
    if source_status is True:
        state, detail = "ok", "检测方报告主合约源码公开（不等于代码已审计）"
    elif source_status is False:
        state, detail = "warn", "源码未开源或未验证，其他安全字段可能不完整"
    else:
        state, detail = "unknown", "无法确认合约源码是否公开"
    push(check("opensource", "合约信息", "源码可验证性", state, detail, "GoPlus / Honeypot.is"))

    in_dex = flag(g.get("is_in_dex"))
    hp_pair = as_dict(h.get("pair"))
    hp_liq = num(hp_pair.get("liquidity"))
    if in_dex is False and hp_liq is None:
        state, detail = "warn", "目前未识别到可交易池；新币未开池时不代表诈骗"
    elif hp_liq is not None and hp_liq < 5000:
        state, detail = "warn", f"Honeypot.is 交易对流动性约 ${hp_liq:,.0f}，偏低"
    elif hp_liq is not None:
        state, detail = "ok", f"Honeypot.is 交易对流动性约 ${hp_liq:,.0f}（可能瞬时撤出）"
    elif in_dex is True:
        state, detail = "unknown", "GoPlus 已识别到 DEX 交易池，但流动性规模未知，无法判断深度"
    else:
        state, detail = "unknown", "交易池 / 流动性信息不可验证"
    push(check("liquidity", "市场风险", "交易池和流动性", state, detail, "GoPlus / Honeypot.is"))

    # This must not be called 'safe' if simulation failed or was unavailable.
    sim_ok = flag(h.get("simulationSuccess"))
    if sim_ok is True:
        push(check("simulation", "交易风险", "买卖模拟", "ok", "Honeypot.is 报告本次模拟执行成功（不代表未来保证卖出）", "Honeypot.is"))
    elif sim_ok is False:
        push(check("simulation", "交易风险", "买卖模拟", "unknown", "模拟失败：" + str(h.get("simulationError") or "原因不明")[:180], "Honeypot.is"))
    else:
        push(check("simulation", "交易风险", "买卖模拟", "unknown", "尚未完成成功的买卖模拟", "Honeypot.is"))

    summary_risk = hsummary.get("risk")
    if summary_risk in ("high", "very_high", "honeypot"):
        push(check("hp_risk", "市场风险", "Honeypot 综合提示", "high", f"官方风险等级：{summary_risk}", "Honeypot.is"))
    elif summary_risk == "medium":
        push(check("hp_risk", "市场风险", "Honeypot 综合提示", "warn", "官方综合风险为 medium", "Honeypot.is"))
    elif present_h and (summary_risk is None or summary_risk == "unknown"):
        push(check("hp_risk", "市场风险", "Honeypot 综合提示", "unknown", "综合评估未知，不能将本次结果视为安全", "Honeypot.is"))
    # Provider summary flags contain independent risks not covered by simulation.
    hp_flags = hsummary.get("flags")
    if isinstance(hp_flags, list):
        order = {"critical": 0, "high": 1, "medium": 2, "warn": 2, "warning": 2}
        prioritized = sorted(hp_flags, key=lambda x: order.get(str(as_dict(x).get("severity") or "").lower(), 9))
        for idx, item in enumerate(prioritized[:12]):
            item = as_dict(item)
            severity = str(item.get("severity") or "").lower()
            if severity not in ("critical", "high", "medium", "warn", "warning"):
                continue
            push(check(f"hp_flag_{idx}", "市场风险", str(item.get("flag") or "服务商风险提示")[:70],
                "high" if severity in ("critical", "high") else "warn",
                str(item.get("description") or "Honeypot.is 标记了潜在风险")[:250], "Honeypot.is"))
        if len(prioritized) > 12:
            push(check("hp_more", "市场风险", "其他 Honeypot 风险标记", "warn", f"还有 {len(prioritized) - 12} 项未展开，请访问官方网站核对完整报告", "Honeypot.is"))

    name = g.get("token_name") or as_dict(h.get("token")).get("name") or "未知代币"
    symbol = g.get("token_symbol") or as_dict(h.get("token")).get("symbol") or ""
    return out, {"name": str(name)[:80], "symbol": str(symbol)[:24], "providerRisk": summary_risk or None}


def normalize_sol(go: dict | None, rug: dict | None) -> tuple[list[dict], dict]:
    g, r = as_dict(go), as_dict(rug)
    out: list[dict] = []
    push = out.append
    power_fields = [
        ("mint", "增发权限", "mintable", "开发者仍可能增发代币"),
        ("freeze", "冻结账户权限", "freezable", "存在冻结用户账户的能力"),
        ("close", "关闭代币账户权限", "closable", "存在关闭代币账户的能力（需核实具体权限范围）"),
        ("mutable_balance", "修改余额权限", "balance_mutable_authority", "存在修改用户代币余额的能力"),
        ("fee_change", "修改转账手续费", "transfer_fee_upgradable", "手续费未来可能被修改"),
        ("hook_change", "修改转账 Hook", "transfer_hook_upgradable", "转账 Hook 可被调整，未来交易行为可能变化"),
        ("state_change", "修改默认账户状态", "default_account_state_upgradable", "默认账户状态可更改"),
        ("metadata", "修改代币资料", "metadata_mutable", "名称/资料可以修改，注意项目冒用", "warn"),
    ]
    rug_token = as_dict(r.get("token"))
    for entry in power_fields:
        id, title, key, msg, *extra = entry
        val = flag(g.get(key))
        # RugCheck full reports use token.*Authority; summary reports use
        # top-level *Authority. Cross-source disagreement must be resolved
        # conservatively: one verified active authority wins over a clean flag.
        rug_key = "mintAuthority" if id == "mint" else "freezeAuthority" if id == "freeze" else None
        if rug_key:
            if rug_key in rug_token:
                rug_value = rug_token[rug_key]
                authority_risk = (False if rug_value is None else True if isinstance(rug_value, str) and rug_value.strip() else None)
            elif rug_key in r:
                rug_value = r[rug_key]
                authority_risk = (False if rug_value is None else True if isinstance(rug_value, str) and rug_value.strip() else None)
            else:
                authority_risk = None
            val = first_known(val, authority_risk)
        elif id == "metadata" and isinstance(as_dict(r.get("tokenMeta")).get("mutable"), bool):
            val = first_known(val, r["tokenMeta"]["mutable"])
        push(boolean_check(id, "权限风险", title, val, msg, "未发现当前有效的对应权限", "GoPlus / RugCheck" if id in ("mint", "freeze", "metadata") else "GoPlus", extra[0] if extra else "high"))

    push(boolean_check("no_transfer", "交易风险", "禁止转账", first_known(g.get("non_transferable"), g.get("none_transferable")),
        "代币被标记为不可转账，可能无法正常交易", "未识别到不可转账限制", "GoPlus"))
    state = str(g.get("default_account_state", ""))
    if state == "2":
        push(check("default_frozen", "交易风险", "新账户默认状态", "high", "新建代币账户默认被冻结", "GoPlus"))
    elif state in ("0", "1"):
        push(check("default_frozen", "交易风险", "新账户默认状态", "ok" if state == "1" else "warn", "默认已初始化" if state == "1" else "默认未初始化，可能暂不可交易", "GoPlus"))
    else:
        push(check("default_frozen", "交易风险", "新账户默认状态", "unknown", "未取得账户状态", "GoPlus"))

    # GoPlus documents an address under transfer_hook, but real API results
    # may return a list of hooks instead of an object. Never silently drop it.
    hook_data = g.get("transfer_hook")
    if isinstance(hook_data, list):
        hook_present = (len(hook_data) > 0)
    elif isinstance(hook_data, dict):
        hook_present = True if hook_data.get("address") else (False if hook_data == {} and "transfer_hook" in g else None)
    else:
        hook_present = None
    push(boolean_check("transfer_hook", "交易风险", "转账 Hook", hook_present,
        "存在外部转账 Hook，可能影响或阻断交易", "未识别到外部转账 Hook", "GoPlus", "warn"))
    hooks = hook_data if isinstance(hook_data, list) else [hook_data] if isinstance(hook_data, dict) else []
    malicious = first_known(*(as_dict(x).get("malicious_address") for x in hooks))
    push(boolean_check("malicious_hook", "交易风险", "恶意转账 Hook 地址", malicious,
        "GoPlus 报告 Hook 地址有恶意关联，可能造成交易损失", "已检查的 Hook 地址未识别到恶意标记", "GoPlus"))

    fees = as_dict(g.get("transfer_fee"))
    # GoPlus's current OpenAPI defines ratios: 0.02 means 2%, NOT 0.0002%.
    # Scheduled fees are an array; also read the legacy single-object shape.
    def sol_fee(value: Any) -> float | None:
        ratio = num(value)
        unit = g.get("_fee_unit", "ratio")
        if unit == "basis_points": return ratio / 100 if ratio is not None and 0 <= ratio <= 10000 else None
        if unit == "unknown": return None
        return percent_tax(ratio, True) if ratio is not None and 0 <= ratio <= 1 else None
    raw_now = as_dict(fees.get("current_fee_rate")).get("fee_rate")
    fee_now = sol_fee(raw_now)
    scheduled = fees.get("scheduled_fee_rate")
    scheduled = scheduled if isinstance(scheduled, list) else [scheduled] if isinstance(scheduled, dict) else []
    future_values = [sol_fee(as_dict(x).get("fee_rate")) for x in scheduled]
    valid_future = [v for v in future_values if v is not None]
    fee_future = max(valid_future) if valid_future else None
    if fee_now is None and fee_future is None:
        push(check("transfer_fee", "交易风险", "当前 / 预定转账手续费", "unknown", "无可验证的转账费率数据", "GoPlus"))
    else:
        def display_fee(value: float) -> str:
            return f"{value:.2f}%" if value == 0 or value >= 0.01 else f"{value:.6g}%"
        now_txt = "当前 " + display_fee(fee_now) if fee_now is not None else "当前未知"
        later_txt = "；预定最高 " + display_fee(fee_future) if fee_future is not None else ""
        max_fee = max(v for v in (fee_now, fee_future) if v is not None)
        state = "high" if max_fee >= 50 else "warn" if max_fee > 0 else "ok" if fee_now is not None and all(v is not None for v in future_values) else "unknown"
        push(check("transfer_fee", "交易风险", "当前 / 预定转账手续费", state, now_txt + later_txt + "；按当前维护配置的费率单位换算，实际扣费还可能受最大收费额限制", "GoPlus"))
    if (raw_now is not None and fee_now is None) or any(v is None for v in future_values):
        push(check("transfer_fee_format", "交易风险", "转账费率数据完整性", "unknown", "部分费率缺失或不符合 GoPlus 文档的 0–1 比例范围，未猜测单位或判定为零费率", "GoPlus"))

    push(boolean_check("rugged", "市场风险", "已发生 RugPull 标记", flag(r.get("rugged")),
        "RugCheck 报告代币有过撤池或项目跑路标记", "RugCheck 未报告已发生 RugPull", "RugCheck"))
    risks = r.get("risks") if isinstance(r.get("risks"), list) else None
    if risks is None:
        push(check("rug", "市场风险", "RugCheck 风险项目", "unknown", "暂时无法读取风险报告项目", "RugCheck"))
    elif len(risks) == 0:
        push(check("rug", "市场风险", "RugCheck 风险项目", "ok", "本次报告未列出风险项，不能保证安全", "RugCheck"))
    else:
        level_order = {"danger": 0, "critical": 0, "high": 0, "error": 0, "warn": 1, "warning": 1, "medium": 1}
        prioritized = sorted(risks, key=lambda x: level_order.get(str(as_dict(x).get("level", "")).lower(), 2))
        for idx, item in enumerate(prioritized[:12]):
            x = as_dict(item)
            label = str(x.get("name") or "未知风险项")[:75]
            sev = str(x.get("level") or "").lower()
            level = ("high" if sev in ("danger", "critical", "high", "error") else
                     "warn" if sev in ("warn", "warning", "medium") else "unknown")
            push(check(f"rug_{idx}", "市场风险", label, level,
                str(x.get("description") or x.get("value") or "RugCheck 仅给出信息项，风险级别未验证")[:300], "RugCheck"))
        if len(prioritized) > 12:
            push(check("rug_more", "市场风险", "其他风险项", "warn", f"另有 {len(prioritized)-12} 项，请打开 RugCheck 官网查看", "RugCheck"))

    # RugCheck full report normally gives LP lock data per pool in markets[*].lp.
    # A top-level lpLockedPct is normally from the summary endpoint. If multiple
    # pools disagree, show the least locked pool, NEVER the best-looking one.
    locks = []
    root_lock = num(r.get("lpLockedPct"))
    if root_lock is not None and 0 <= root_lock <= 100:
        locks.append(root_lock)
    for market in (r.get("markets") if isinstance(r.get("markets"), list) else []):
        lp = as_dict(as_dict(market).get("lp"))
        value = num(lp.get("lpLockedPct"))
        if value is not None and 0 <= value <= 100:
            locks.append(value)
    if not locks:
        push(check("lp_lock", "市场风险", "流动性锁定比例", "unknown", "RugCheck 未提供可用锁定比例", "RugCheck"))
    else:
        locked = min(locks)
        pool_label = "（多池取最低值）" if len(locks) > 1 else ""
        push(check("lp_lock", "市场风险", "流动性锁定比例", "warn" if locked < 90 else "ok",
            f"RugCheck 所报告池子的锁定比例 {locked:g}%{pool_label}；不代表其他交易池或未来的流动性安全", "RugCheck"))
    score = num(r.get("score_normalised"))
    if score is None:
        score = num(r.get("score"))
    if r:
        reported_at = r.get("detectedAt")
        # detectedAt is not a verified last-scan timestamp. Do not promise freshness.
        push(check("report_age", "合约信息", "RugCheck 数据时效", "unknown",
            ("服务商 detectedAt：" + str(reported_at)[:40] + "；未确认此字段代表最新扫描时间，当前链上状态尚未独立复核") if reported_at else "服务商未提供可验证的最新扫描时间，不能确认数据新鲜度", "RugCheck"))
    meta = as_dict(g.get("metadata"))
    token_meta = as_dict(r.get("tokenMeta"))
    name = meta.get("name") or token_meta.get("name") or "未知代币"
    symbol = meta.get("symbol") or token_meta.get("symbol") or ""
    return out, {"name": str(name)[:80], "symbol": str(symbol)[:24], "rugScore": score, "rugRisk": r.get("riskLevel")}


def check_token(chain: str, address: str) -> dict:
    address = normalize_address(chain, address)
    endpoints = {"GoPlus": goplus, "Honeypot.is": honeypot} if chain != "sol" else {"GoPlus": goplus, "RugCheck": rugcheck}
    sources: dict[str, dict] = {}
    data: dict[str, dict | None] = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = {name: pool.submit(fn, chain, address) for name, fn in endpoints.items()}
        for name, task in tasks.items():
            try:
                data[name] = task.result()
                sources[name] = {"status": "ok", "detail": "检测结果已获取"}
            except Exception as exc:
                data[name] = None
                # Never expose a token/stacktrace or a full error from a remote upstream.
                sources[name] = {"status": "unavailable", "detail": str(exc)[:125] if isinstance(exc, DataError) else "接口异常或超时"}
    checks, token = (normalize_sol(data.get("GoPlus"), data.get("RugCheck")) if chain == "sol"
                     else normalize_evm(data.get("GoPlus"), data.get("Honeypot.is")))
    checks = runtime_policy.localize_checks(checks)
    counts = {v: sum(x["state"] == v for x in checks) for v in ("high", "warn", "ok", "unknown")}
    all_available = all(p["status"] == "ok" for p in sources.values())
    if not any(p["status"] == "ok" for p in sources.values()):
        level, title = "unknown", "检测服务暂不可用"
    elif counts["high"]:
        level, title = "high", "发现高危风险"
    elif counts["warn"]:
        level, title = "warn", "发现需要警惕的风险"
    elif not all_available or counts["unknown"]:
        level, title = "unknown", "部分项目尚未验证"
    else:
        level, title = "ok", "暂未发现已知高危"
    return {
        "chain": chain, "address": address, "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": level, "title": title, "counts": counts, "token": token,
        "sources": sources, "checks": checks, "complete": all_available and counts["unknown"] == 0,
        "notice": "仅为第三方接口的即时风险初筛，不是审计、不构成投资建议。未显示风险不代表安全，开池及权限状态可随时变化。",
    }
