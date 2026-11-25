from pathlib import Path

def test_android_credential_vault_is_keystore_backed_and_not_readable_from_js():
    script = Path("scripts/add-android-secure-credentials.py").read_text()
    assert "AndroidKeyStore" in script
    assert "AES/GCM/NoPadding" in script
    assert "setRandomizedEncryptionRequired(true)" in script
    assert "saveBinanceTestnetCredentials" in script
    assert "binanceTestnetCredentialStatus" in script
    assert "clearBinanceTestnetCredentials" in script
    assert "getBinanceTestnetAccount" in script
    assert "loadForNativeUse" in script
    assert "saveGmgnApiKey" in script
    assert "gmgnApiKeyStatus" in script
    assert "clearGmgnApiKey" in script
    assert "loadGmgnApiKeyForNativeUse" in script
    assert "payload.indexOf('\\n')" in script
    assert "engine.binance_android" in script
    assert "call.resolve(apiSecret)" not in script
    assert "apiSecret" in script
    assert "call.resolve" in script
    assert "call.resolve(apiSecret)" not in script
    assert "Log." not in script
