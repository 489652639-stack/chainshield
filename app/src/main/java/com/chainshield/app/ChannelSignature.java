package com.chainshield.app;

import java.security.KeyFactory;
import java.security.Signature;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;

/** Verify exact bytes with the app's pinned key; never trusts a key from the server. */
public final class ChannelSignature {
    private ChannelSignature() { }
    public static boolean verify(byte[] publicDer, byte[] payload, byte[] signature) {
        if (payload.length > 65536 || signature.length > 1024) return false;
        try {
            RSAPublicKey key = (RSAPublicKey) KeyFactory.getInstance("RSA")
                .generatePublic(new X509EncodedKeySpec(publicDer));
            if (key.getModulus().bitLength() < 2048) return false;
            Signature verifier = Signature.getInstance("SHA256withRSA");
            verifier.initVerify(key);
            verifier.update(payload);
            return verifier.verify(signature);
        } catch (Exception ignored) { return false; }
    }
}
