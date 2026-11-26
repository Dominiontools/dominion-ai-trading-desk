"""Configure the generated Capacitor Android project with embedded Python.

Adds Chaquopy, copies the paper-only Python engine into the APK, registers a
foreground service and a Capacitor bridge, and restricts cleartext access to
localhost only. This runs after `npx cap add android`.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android"
APP = ANDROID / "app"
PACKAGE = "com.dominion.aitradingdesk"
CHAQUOPY_VERSION = "16.1.0"


def require(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Required generated Android file not found: {path}")
    return path.read_text(encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def configure_gradle() -> None:
    root_gradle = ANDROID / "build.gradle"
    root_text = require(root_gradle)
    classpath = f"com.chaquo.python:gradle:{CHAQUOPY_VERSION}"
    if classpath not in root_text:
        if re.search(r"plugins\s*\{", root_text):
            root_text, count = re.subn(
                r"(plugins\s*\{)",
                r"\1\n    id 'com.chaquo.python' version '" + CHAQUOPY_VERSION + "' apply false",
                root_text, count=1,
            )
        else:
            root_text, count = re.subn(
                r"(dependencies\s*\{)",
                r"\1\n        classpath '" + classpath + "'",
                root_text, count=1,
            )
        if count != 1:
            raise SystemExit("Could not safely add Chaquopy to the root Gradle file.")
        write(root_gradle, root_text)

    app_gradle = APP / "build.gradle"
    app_text = require(app_gradle)
    if "com.chaquo.python" not in app_text:
        if re.search(r"plugins\s*\{", app_text):
            app_text, count = re.subn(r"(plugins\s*\{)", r"\1\n    id 'com.chaquo.python'", app_text, count=1)
        else:
            app_text = re.sub(
                r"(apply plugin:\s*['\"]com\.android\.application['\"]\s*)",
                r"\1\napply plugin: 'com.chaquo.python'\n",
                app_text, count=1,
            )
            count = 1 if "apply plugin: 'com.chaquo.python'" in app_text else 0
        if count != 1:
            raise SystemExit("Could not safely apply Chaquopy to the app Gradle file.")

    app_text, min_count = re.subn(r"(minSdkVersion\s+)(\d+)", r"\g<1>24", app_text, count=1)
    if min_count == 0:
        app_text, min_count = re.subn(r"(minSdk\s*=\s*)(\d+)", r"\g<1>24", app_text, count=1)
    if min_count == 0 and "rootProject.ext.minSdkVersion" in app_text:
        variables = ANDROID / "variables.gradle"
        variables_text = require(variables)
        variables_text, min_count = re.subn(r"(minSdkVersion\s*=\s*)(\d+)", r"\g<1>24", variables_text, count=1)
        if min_count:
            write(variables, variables_text)
    if min_count == 0:
        raise SystemExit("Could not find minSdkVersion; Chaquopy requires Android API 24 or newer.")

    if "abiFilters" not in app_text:
        app_text, count = re.subn(
            r"(defaultConfig\s*\{)",
            r"\1\n        ndk { abiFilters 'arm64-v8a', 'x86_64' }",
            app_text, count=1,
        )
        if count != 1:
            raise SystemExit("Could not add supported Android CPU architectures.")

    if "chaquopy {" not in app_text:
        app_text += "\n\nchaquopy {\n    defaultConfig {\n        version = '3.11'\n    }\n}\n"
    write(app_gradle, app_text)


def configure_python_sources() -> None:
    source = APP / "src" / "main" / "python" / "engine"
    source.mkdir(parents=True, exist_ok=True)
    (source / "__init__.py").write_text('"""Dominion embedded paper engine."""\n', encoding="utf-8")
    for name in ("crypto_arbitrage.py", "crypto_feeds.py", "crypto_monitor.py",
                 "crypto_api.py", "crypto_service.py", "crypto_strategy.py",
                 "paper_workflow.py", "strategies.py", "confluence_strategy.py", "market_data.py",
                 "specialist_agents.py", "agent_feeds.py", "positions.py",
                 "risk.py", "quotes.py", "readiness.py", "binance_testnet.py", "risk_execution.py", "binance_protection.py", "binance_lifecycle.py", "binance_android.py", "binance_market_rules.py", "binance_signal_router.py", "binance_daily_loss.py", "binance_risk_context.py", "crypto_universe.py"):
        shutil.copy2(ROOT / "engine" / name, source / name)


def configure_manifest() -> None:
    manifest = APP / "src" / "main" / "AndroidManifest.xml"
    text = require(manifest)
    for permission in (
        "android.permission.FOREGROUND_SERVICE",
        "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",
        "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
        "android.permission.FOREGROUND_SERVICE_DATA_SYNC",
        "android.permission.POST_NOTIFICATIONS",
        "android.permission.INTERNET",
    ):
        tag = f'<uses-permission android:name="{permission}" />'
        if tag not in text:
            text = text.replace("<application", tag + "\n    <application", 1)

    attribute = 'android:networkSecurityConfig="@xml/network_security_config"'
    if attribute not in text:
        text = text.replace("<application", f"<application {attribute}", 1)

    if "TradingEngineService" not in text:
        service = f'''
        <service
            android:name="{PACKAGE}.TradingEngineService"
            android:exported="false"
            android:foregroundServiceType="dataSync|specialUse">
            <property
                android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
                android:value="User-started local paper market monitoring; no live order execution" />
        </service>
'''
        text = text.replace("</application>", service + "    </application>")
    write(manifest, text)

    xml_dir = APP / "src" / "main" / "res" / "xml"
    write(xml_dir / "network_security_config.xml", """<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false" />
  <domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">localhost</domain>
  </domain-config>
</network-security-config>
""")


PLUGIN_JAVA = r'''package com.dominion.aitradingdesk;

import android.content.Intent;
import androidx.core.content.ContextCompat;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "TradingEngine")
public class TradingEnginePlugin extends Plugin {
    @PluginMethod
    public void start(PluginCall call) {
        try {
            Intent intent = new Intent(getContext(), TradingEngineService.class);
            ContextCompat.startForegroundService(getContext(), intent);
            JSObject result = new JSObject();
            result.put("accepted", true);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Could not start the phone engine.", error);
        }
    }

    @PluginMethod
    public void stop(PluginCall call) {
        try {
            boolean stopped = getContext().stopService(
                new Intent(getContext(), TradingEngineService.class));
            JSObject result = new JSObject();
            result.put("stopped", stopped);
            call.resolve(result);
        } catch (Exception error) {
            call.reject("Could not stop the phone engine.", error);
        }
    }

    @PluginMethod
    public void status(PluginCall call) {
        JSObject result = new JSObject();
        result.put("running", TradingEngineService.isRunning());
        result.put("error", TradingEngineService.lastError());
        call.resolve(result);
    }
}
'''


SERVICE_JAVA = r'''package com.dominion.aitradingdesk;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.util.Log;
import androidx.core.app.NotificationCompat;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

public class TradingEngineService extends Service {
    private static final String TAG = "DominionEngine";
    private static final String CHANNEL_ID = "dominion_trading_engine";
    private static final int NOTIFICATION_ID = 7301;
    private static volatile boolean running = false;
    private static volatile String lastError = "";
    private Thread startupThread;

    public static boolean isRunning() { return running; }
    public static String lastError() { return lastError; }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForegroundForApi(notification("Starting paper market monitor…"));
        if (startupThread == null || !startupThread.isAlive()) {
            startupThread = new Thread(this::startPythonEngine, "dominion-python-start");
            startupThread.start();
        }
        return START_STICKY;
    }

    private void startForegroundForApi(Notification notification) {
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        }
    }

    private void startPythonEngine() {
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(getApplicationContext()));
            }
            PyObject module = Python.getInstance().getModule("engine.crypto_service");
            CredentialVault vault = new CredentialVault(getApplicationContext());
            String binanceRecoveryJson = "{\"status\":\"SKIPPED\",\"halted\":true,\"orders_enabled\":false}";
            String[] binanceCredentials = null;
            boolean binanceOrdersEnabled = false;
            if (vault.hasCredentials()) {
                try {
                    binanceCredentials = vault.loadForNativeUse();
                    PyObject recovery = Python.getInstance().getModule("engine.binance_android");
                    String dataDirectory = getFilesDir().getAbsolutePath();
                    String recoveryJson = recovery.callAttr("account_risk_snapshot",
                        binanceCredentials[0], binanceCredentials[1],
                        dataDirectory + "/binance-lifecycle.json",
                        dataDirectory + "/binance-daily-loss.jsonl").toString();
                    binanceRecoveryJson = recoveryJson;
                    binanceOrdersEnabled = vault.binanceTestnetOrdersEnabled();
                } catch (Exception recoveryError) {
                    Log.w(TAG, "Binance Testnet recovery remains blocked; manual review required.");
                    binanceOrdersEnabled = false;
                }
            }
            String binanceApiKey = binanceOrdersEnabled && binanceCredentials != null ? binanceCredentials[0] : "";
            String binanceApiSecret = binanceOrdersEnabled && binanceCredentials != null ? binanceCredentials[1] : "";
            PyObject result;
            try {
                result = module.callAttr("start_embedded",
                    getFilesDir().getAbsolutePath(), 8766, binanceRecoveryJson,
                    binanceApiKey, binanceApiSecret, binanceOrdersEnabled);
            } finally {
                if (binanceCredentials != null) {
                    binanceCredentials[0] = null;
                    binanceCredentials[1] = null;
                }
            }
            running = true;
            lastError = "";
            Log.i(TAG, "Embedded trading engine started: " + result.toString());
            NotificationManager manager = getSystemService(NotificationManager.class);
            String engineMessage = binanceOrdersEnabled
                ? "Binance Spot Testnet automation is enabled"
                : "Paper monitor is running";
            if (manager != null) manager.notify(NOTIFICATION_ID, notification(engineMessage));
        } catch (Exception error) {
            running = false;
            lastError = error.getClass().getSimpleName() + ": " + error.getMessage();
            Log.e(TAG, "Could not start embedded Python engine", error);
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.notify(NOTIFICATION_ID, notification("Engine error — open the app"));
        }
    }

    private Notification notification(String text) {
        Intent openApp = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent pending = openApp == null ? null :
            PendingIntent.getActivity(this, 0, openApp,
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(getApplicationInfo().icon)
            .setContentTitle("Dominion AI Trading Desk")
            .setContentText(text)
            .setContentIntent(pending)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID, "Trading engine", NotificationManager.IMPORTANCE_LOW);
            channel.setDescription("Shows when the user-started paper market monitor is running.");
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) manager.createNotificationChannel(channel);
        }
    }

    private void stopPythonEngine() {
        try {
            if (Python.isStarted()) {
                Python.getInstance().getModule("engine.crypto_service").callAttr("stop_embedded");
            }
        } catch (Exception error) {
            Log.w(TAG, "Error while stopping embedded Python engine", error);
        }
        running = false;
    }

    @Override
    public void onDestroy() {
        stopPythonEngine();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
'''


def configure_native_bridge() -> None:
    java_dir = APP / "src" / "main" / "java" / PACKAGE.replace(".", "/")
    write(java_dir / "TradingEnginePlugin.java", PLUGIN_JAVA)
    write(java_dir / "TradingEngineService.java", SERVICE_JAVA)

    candidates = list((APP / "src" / "main").rglob("MainActivity.java"))
    if not candidates:
        raise SystemExit("Capacitor MainActivity.java was not found.")
    activity = candidates[0]
    text = require(activity)
    if "TradingEnginePlugin" not in text:
        package_line = re.search(r"^package\s+[\w.]+;", text, re.M)
        if not package_line:
            raise SystemExit("Could not identify MainActivity package.")
        text = text[:package_line.end()] + "\n\nimport android.os.Bundle;\nimport com.dominion.aitradingdesk.TradingEnginePlugin;" + text[package_line.end():]
        if "onCreate(" in text:
            text = re.sub(
                r"(protected void onCreate\(Bundle savedInstanceState\)\s*\{)",
                r"\1\n        registerPlugin(TradingEnginePlugin.class);",
                text, count=1,
            )
        else:
            text = text.rsplit("}", 1)[0] + """
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(TradingEnginePlugin.class);
        super.onCreate(savedInstanceState);
    }
}
"""
        write(activity, text)


def main() -> None:
    if not APP.exists():
        raise SystemExit("Android project not found; run npx cap add android first.")
    configure_gradle()
    configure_python_sources()
    configure_manifest()
    configure_native_bridge()
    print("Configured embedded Python paper engine and Android foreground-service bridge.")


if __name__ == "__main__":
    main()
