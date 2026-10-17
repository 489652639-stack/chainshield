"""Fixture-only tests: these posts are not actual statements or GMGN deliveries."""
import copy
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from radar.core import Radar, Store
from radar.server import make_handler
from radar.social import WATCHLIST
from radar.tests.test_flow import Fake, NOW


def message(**patch):
    return dict(platform='X', handle='elonmusk', text='Nebulax launches rocket',
                published=NOW, url='https://x.com/elonmusk/status/123456789',
                kind='post', **patch)


class Social(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        self.api = Fake()
        self.api.news = lambda: []
        self.radar = Radar(self.store, self.api, lambda: NOW)

    def tearDown(self):
        self.store.db.close()

    def test_person_speech_can_trigger_paper_without_two_news_domains(self):
        self.assertEqual(self.radar.ingest_social([message()])['accepted'], 1)
        self.radar.cycle()
        state = self.radar.snapshot()
        self.assertEqual(len(state['positions']), 1)
        self.assertFalse(state['live_available'])
        self.assertFalse(state['social']['connected'])
        self.assertEqual(len(state['social']['accounts']), 20)
        self.assertEqual(len(state['social']['messages']), 1)

    def test_same_post_is_deduped_after_radar_restart(self):
        self.radar.ingest_social([message()])
        second = Radar(self.store, self.api, lambda: NOW)
        self.assertEqual(second.ingest_social([message()])['duplicates'], 1)
        self.assertEqual(len(second.snapshot()['social']['messages']), 1)

    def test_no_impostor_profile_link_cross_account_stale_or_future_input(self):
        for patch in ({'handle': 'aeyakovenko123'}, {'url': 'https://x.com/elonmusk'},
                      {'url': 'https://x.com/binance/status/123456789'},
                      {'url': 'https://x.com.evil.example/elonmusk/status/123456789'},
                      {'url': 'https://x.com/elonmusk/status/123456789?token=secret'},
                      {'published': NOW - 1801}, {'published': NOW + 61},
                      {'published': float('nan')}, {'text': ''}):
            bad = {**message(), **patch}
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.radar.ingest_social([message(), bad])
            self.assertFalse(self.store.rows('SELECT * FROM social_messages'))
            self.assertFalse(self.store.rows('SELECT * FROM topics'))

    def test_trump_two_platforms_and_retweet_attribution(self):
        x = {**message(), 'handle': 'realDonaldTrump', 'url': 'https://x.com/realDonaldTrump/status/123456789'}
        truth = {**x, 'platform': 'TRUTH_SOCIAL', 'url': 'https://truthsocial.com/@realDonaldTrump/posts/123456789'}
        for m in (x, truth):
            m['kind'] = 'repost'
        self.assertEqual(self.radar.ingest_social([x, truth])['accepted'], 2)
        self.radar.cycle()
        self.assertFalse(self.radar.snapshot()['positions'])
        self.assertEqual(len(self.radar.snapshot()['social']['messages']), 2)

    def test_safety_block_and_pause_apply_to_person_speech(self):
        self.radar.ingest_social([message()])
        self.api.danger = True
        self.radar.cycle()
        self.assertFalse(self.radar.snapshot()['positions'])
        self.api.danger = False
        self.store.set('enabled', 'false')
        self.radar.cycle()
        self.assertFalse(self.radar.snapshot()['positions'])

    def test_intake_auth_and_live_still_disabled(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.radar, 'x' * 32))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = 'http://127.0.0.1:' + str(server.server_port) + '/api/social/import'
        body = json.dumps({'messages': [message()]}).encode()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url, data=body))
            self.assertEqual(error.exception.code, 401)
            self.assertFalse(self.store.rows('SELECT * FROM social_messages'))
            with urlopen(Request(url, data=body, headers={'Authorization': 'Bearer ' + 'x' * 32})) as response:
                self.assertEqual(json.load(response)['accepted'], 1)
            self.assertFalse(self.radar.snapshot()['live_available'])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
