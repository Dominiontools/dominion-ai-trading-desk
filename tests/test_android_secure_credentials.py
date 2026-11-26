from pathlib import Path

def test_android_credential_vault_is_keystore_backed_and_not_readable_from_js():
    script = Path("scripts/add-android-secure-credentials.py").read_text()
    assert "AndroidKeyStore" in script
    assert "AES/GCM/NoPadding" in script
    assert "setRandomizedEncryptionRequired(true)" in script
    assert "saveBinanceTestnetCredentials" in script
    assert "binanceTestnetCredentialStatus" in script
    assert "clearBinanceTestnetCredentials" in script
    assert "binanceTestnetOrdersEnabled" in script
    assert "setBinanceTestnetOrdersEnabled" in script
    assert "BINANCE_ORDERS_ENABLED" in script
    assert 'prefs.getBoolean(BINANCE_ORDERS_ENABLED, false)' in script
    assert "if (enabled && !hasCredentials())" in script
    assert ".remove(BINANCE_ORDERS_ENABLED)" in script
    assert "getBinanceTestnetAccount" in script
    assert "loadForNativeUse" in script
    assert "Gmgn" not in script
    assert "GMGN" not in script
    assert 'prefs.edit().clear()' not in script
    assert "payload.indexOf('\\n')" in script
    assert "engine.binance_android" in script
    assert "call.resolve(apiSecret)" not in script
    assert "apiSecret" in script
    assert "call.resolve" in script
    assert "call.resolve(apiSecret)" not in script
    assert "Log." not in script


def test_android_python_bundle_excludes_unused_gmgn_integration():
    script = Path("scripts/configure-android-local-api.py").read_text()
    assert "gmgn_api.py" not in script
    assert "gmgn_sniper.py" not in script
    assert 'callAttr("start_embedded"' in script
    assert "Gmgn" not in script
    assert "GMGN" not in script


def test_android_python_bundle_includes_restart_safe_binance_lifecycle_module():
    script = Path("scripts/configure-android-local-api.py").read_text()
    assert '"binance_lifecycle.py"' in script
    assert '"risk_execution.py"' in script
    assert '"binance_protection.py"' in script


def test_android_service_passes_restart_recovery_into_safe_status_provider():
    script = Path("scripts/configure-android-local-api.py").read_text()
    assert 'String binanceRecoveryJson' in script
    assert 'binanceApiKey, binanceApiSecret, binanceOrdersEnabled);' in script
    assert 'callAttr("account_risk_snapshot"' in script
    assert 'binanceOrdersEnabled = vault.binanceTestnetOrdersEnabled()' in script
    assert 'binanceOrdersEnabled && binanceCredentials != null' in script
    assert 'binanceApiKey, binanceApiSecret, binanceOrdersEnabled' in script


def test_android_python_bundle_includes_verified_context_signal_router():
    script = Path("scripts/configure-android-local-api.py").read_text()
    assert '"binance_signal_router.py"' in script


def test_android_python_bundle_includes_daily_loss_and_verified_risk_context():
    script = Path("scripts/configure-android-local-api.py").read_text()
    assert '"binance_daily_loss.py"' in script
    assert '"binance_risk_context.py"' in script


def test_android_default_recovery_json_has_valid_java_escaping():
    script = Path("scripts/configure-android-local-api.py").read_text()
    line = next(line for line in script.splitlines()
                if "String binanceRecoveryJson" in line)
    prefix = line.split("status")[0]
    assert prefix.endswith(chr(92) + '"')
    assert not prefix.endswith(chr(92) * 2 + '"')
