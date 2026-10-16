"""Exercise the production Java RSA verifier on the host JDK, with real signatures."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        java=os.environ.get('JAVA_HOME','')
        javac=str(Path(java)/'bin/javac') if java else 'javac'
        java=str(Path(java)/'bin/java') if java else 'java'
        subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(root/'key.pem')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True)
        subprocess.run(['openssl','pkey','-in',str(root/'key.pem'),'-pubout','-outform','DER','-out',str(root/'key.der')],check=True)
        (root/'payload').write_bytes(b'{"schema":1,"test":true}')
        subprocess.run(['openssl','dgst','-sha256','-sign',str(root/'key.pem'),'-out',str(root/'signature'),str(root/'payload')],check=True)
        harness=root/'VerifyHarness.java'
        harness.write_text('''import java.nio.file.*; import com.chainshield.app.ChannelSignature;
public class VerifyHarness {
 public static void main(String[] a) throws Exception {
  byte[] key=Files.readAllBytes(Paths.get(a[0])), data=Files.readAllBytes(Paths.get(a[1])), sig=Files.readAllBytes(Paths.get(a[2]));
  if(!ChannelSignature.verify(key,data,sig))throw new AssertionError("valid signature");
  data[0]^=1; if(ChannelSignature.verify(key,data,sig))throw new AssertionError("mutated payload"); data[0]^=1;
  sig[0]^=1; if(ChannelSignature.verify(key,data,sig))throw new AssertionError("mutated signature");
  if(ChannelSignature.verify(key,data,new byte[0]))throw new AssertionError("empty signature");
  if(ChannelSignature.verify(key,new byte[65537],sig))throw new AssertionError("oversized payload");
  if(ChannelSignature.verify(new byte[0],data,sig))throw new AssertionError("malformed key");
  if(ChannelSignature.verify(key,data,new byte[1025]))throw new AssertionError("oversized signature");
  System.out.println("生产签名校验器：7 组真实密码学检查通过");
 }
}''')
        subprocess.run([javac,'-encoding','UTF-8','-d',str(root),str(ROOT/'app/src/main/java/com/chainshield/app/ChannelSignature.java'),str(harness)],check=True)
        subprocess.run([java,'-cp',str(root),'VerifyHarness',str(root/'key.der'),str(root/'payload'),str(root/'signature')],check=True)


if __name__=='__main__': run()
