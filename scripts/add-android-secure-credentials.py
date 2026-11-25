"""Add Android Keystore-backed storage for exchange testnet credentials.

The vault is native-only: credentials are encrypted with an Android Keystore
AES-GCM key and are never returned to JavaScript or written to logs/files.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA_DIR = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "dominion" / "aitradingdesk"
PLUGIN = JAVA_DIR / "TradingEnginePlugin.java"

VAULT = r'''package com.dominion.aitradingdesk;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Encrypted local credential storage. Never expose decrypted values to WebView. */
final class CredentialVault {
    private static final String STORE = "dominion_exchange_vault";
    private static final String KEY_ALIAS = "dominion_exchange_aes_gcm_v1";
    private static final String CIPHERTEXT = "credentials_v1";
    private static final String IV = "iv_v1";
    private static final String GMGN_CIPHERTEXT = "gmgn_api_key_v1";
    private static final String GMGN_IV = "gmgn_api_iv_v1";
    private final SharedPreferences prefs;

    CredentialVault(Context context) {
        prefs = context.getSharedPreferences(STORE, Context.MODE_PRIVATE);
    }

    synchronized void save(String apiKey, String apiSecret) throws Exception {
        if (apiKey == null || apiSecret == null ||
            apiKey.length() < 10 || apiKey.length() > 256 ||
            apiSecret.length() < 20 || apiSecret.length() > 256 ||
            apiKey.trim().length() != apiKey.length() ||
            apiSecret.trim().length() != apiSecret.length()) {
            throw new IllegalArgumentException("Invalid API credential format.");
        }
        String payload = apiKey + "\n" + apiSecret;
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] encrypted = cipher.doFinal(payload.getBytes(StandardCharsets.UTF_8));
        boolean committed = prefs.edit()
            .putString(IV, Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
            .putString(CIPHERTEXT, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .commit();
        if (!committed) throw new IllegalStateException("Could not persist encrypted credentials.");
    }

    synchronized boolean hasCredentials() {
        return prefs.contains(IV) && prefs.contains(CIPHERTEXT);
    }

    synchronized void saveGmgnApiKey(String apiKey) throws Exception {
        if (apiKey == null || apiKey.trim().length() < 12 ||
            apiKey.length() > 512 || apiKey.trim().length() != apiKey.length()) {
            throw new IllegalArgumentException("Invalid GMGN API key format.");
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] encrypted = cipher.doFinal(apiKey.getBytes(StandardCharsets.UTF_8));
        boolean committed = prefs.edit()
            .putString(GMGN_IV, Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
            .putString(GMGN_CIPHERTEXT, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .commit();
        if (!committed) throw new IllegalStateException("Could not persist GMGN API key.");
    }

    synchronized boolean hasGmgnApiKey() {
        return prefs.contains(GMGN_IV) && prefs.contains(GMGN_CIPHERTEXT);
    }

    synchronized String loadGmgnApiKeyForNativeUse() throws Exception {
        String encodedIv = prefs.getString(GMGN_IV, null);
        String encodedCiphertext = prefs.getString(GMGN_CIPHERTEXT, null);
        if (encodedIv == null || encodedCiphertext == null) {
            throw new IllegalStateException("No saved GMGN API key.");
        }
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(),
            new GCMParameterSpec(128, Base64.decode(encodedIv, Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(encodedCiphertext, Base64.NO_WRAP)),
            StandardCharsets.UTF_8);
    }

    synchronized void clearGmgnApiKey() {
        prefs.edit().remove(GMGN_IV).remove(GMGN_CIPHERTEXT).commit();
    }

    /** Decrypt only for native in-process exchange use; never bridge this result to JS. */
    synchronized String[] loadForNativeUse() throws Exception {
        String encodedIv = prefs.getString(IV, null);
        String encodedCiphertext = prefs.getString(CIPHERTEXT, null);
        if (encodedIv == null || encodedCiphertext == null) {
            throw new IllegalStateException("No saved Testnet credentials.");
        }
        byte[] iv = Base64.decode(encodedIv, Base64.NO_WRAP);
        byte[] ciphertext = Base64.decode(encodedCiphertext, Base64.NO_WRAP);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), new GCMParameterSpec(128, iv));
        String payload = new String(cipher.doFinal(ciphertext), StandardCharsets.UTF_8);
        int separator = payload.indexOf('\n');
        if (separator <= 0 || separator == payload.length() - 1) {
            throw new IllegalStateException("Stored credential data is invalid.");
        }
        return new String[] { payload.substring(0, separator), payload.substring(separator + 1) };
    }

    synchronized void clear() throws Exception {
        if (!prefs.edit().clear().commit()) {
            throw new IllegalStateException("Could not clear stored credentials.");
        }
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY_ALIAS)) store.deleteEntry(KEY_ALIAS);
    }

    private SecretKey getOrCreateKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (store.containsAlias(KEY_ALIAS)) {
            return ((KeyStore.SecretKeyEntry) store.getEntry(KEY_ALIAS, null)).getSecretKey();
        }
        KeyGenerator generator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build());
        return generator.generateKey();
    }
}
'''

def main():
    if not PLUGIN.exists():
        raise SystemExit("Generated TradingEnginePlugin.java not found.")
    JAVA_DIR.mkdir(parents=True, exist_ok=True)
    (JAVA_DIR / "CredentialVault.java").write_text(VAULT, encoding="utf-8")
    text = PLUGIN.read_text(encoding="utf-8")
    if "saveBinanceTestnetCredentials" not in text:
        methods = r'''
    @PluginMethod
    public void saveBinanceTestnetCredentials(PluginCall call) {
        String apiKey = call.getString("apiKey");
        String apiSecret = call.getString("apiSecret");
        try {
            new CredentialVault(getContext()).save(apiKey, apiSecret);
            JSObject result = new JSObject();
            result.put("saved", true);
            result.put("storage", "ANDROID_KEYSTORE_AES_GCM");
            call.resolve(result);
        } catch (IllegalArgumentException error) {
            call.reject("The API credentials are not in an accepted format.");
        } catch (Exception error) {
            call.reject("Could not securely save the Testnet credentials.");
        }
    }

    @PluginMethod
    public void binanceTestnetCredentialStatus(PluginCall call) {
        JSObject result = new JSObject();
        result.put("saved", new CredentialVault(getContext()).hasCredentials());
        result.put("storage", "ANDROID_KEYSTORE_AES_GCM");
        call.resolve(result);
    }

    @PluginMethod
    public void getBinanceTestnetAccount(PluginCall call) {
        String[] credentials = null;
        try {
            credentials = new CredentialVault(getContext()).loadForNativeUse();
            if (!com.chaquo.python.Python.isStarted()) {
                com.chaquo.python.Python.start(
                    new com.chaquo.python.android.AndroidPlatform(getContext()));
            }
            com.chaquo.python.PyObject module = com.chaquo.python.Python.getInstance()
                .getModule("engine.binance_android");
            String json = module.callAttr("account_summary", credentials[0], credentials[1]).toString();
            JSObject result = new JSObject(json);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Could not read the Binance Spot Testnet account. Check the saved Testnet credentials and network.");
        } finally {
            if (credentials != null) {
                credentials[0] = null;
                credentials[1] = null;
            }
        }
    }

    @PluginMethod
    public void saveGmgnApiKey(PluginCall call) {
        String apiKey = call.getString("apiKey");
        try {
            new CredentialVault(getContext()).saveGmgnApiKey(apiKey);
            JSObject result = new JSObject();
            result.put("saved", true);
            result.put("storage", "ANDROID_KEYSTORE_AES_GCM");
            call.resolve(result);
        } catch (IllegalArgumentException error) {
            call.reject("The GMGN API key is not in an accepted format.");
        } catch (Exception error) {
            call.reject("Could not securely save the GMGN API key.");
        }
    }

    @PluginMethod
    public void gmgnApiKeyStatus(PluginCall call) {
        JSObject result = new JSObject();
        result.put("saved", new CredentialVault(getContext()).hasGmgnApiKey());
        result.put("storage", "ANDROID_KEYSTORE_AES_GCM");
        call.resolve(result);
    }

    @PluginMethod
    public void clearGmgnApiKey(PluginCall call) {
        try {
            new CredentialVault(getContext()).clearGmgnApiKey();
            JSObject result = new JSObject();
            result.put("cleared", true);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Could not clear the saved GMGN API key.");
        }
    }

    @PluginMethod
    public void clearBinanceTestnetCredentials(PluginCall call) {
        try {
            new CredentialVault(getContext()).clear();
            JSObject result = new JSObject();
            result.put("cleared", true);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Could not clear the saved Testnet credentials.");
        }
    }
'''
        marker = "\n}"
        index = text.rfind(marker)
        if index < 0:
            raise SystemExit("Could not find end of TradingEnginePlugin class.")
        text = text[:index] + "\n" + methods + text[index:]
        PLUGIN.write_text(text, encoding="utf-8")
    print("Configured Android Keystore-backed credential vault.")

if __name__ == "__main__":
    main()
