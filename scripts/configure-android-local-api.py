"""Apply a localhost-only cleartext exception for the Android WebView bridge."""
from pathlib import Path

manifest = Path("android/app/src/main/AndroidManifest.xml")
if not manifest.exists():
    raise SystemExit("AndroidManifest.xml not found; run npx cap add android first.")

text = manifest.read_text(encoding="utf-8")
attribute = 'android:networkSecurityConfig="@xml/network_security_config"'
if attribute not in text:
    text = text.replace("<application", f"<application {attribute}", 1)
    manifest.write_text(text, encoding="utf-8")

xml_dir = Path("android/app/src/main/res/xml")
xml_dir.mkdir(parents=True, exist_ok=True)
(xml_dir / "network_security_config.xml").write_text(
    """<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <base-config cleartextTrafficPermitted="false" />
  <domain-config cleartextTrafficPermitted="true">
    <domain includeSubdomains="false">localhost</domain>
  </domain-config>
</network-security-config>
""",
    encoding="utf-8",
)
print("Android local API networking restricted to localhost.")
