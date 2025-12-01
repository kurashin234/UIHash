try:
    from androguard.core.apk import APK
    from androguard.core.axml import AXMLPrinter
    print("Imports successful")
except ImportError as e:
    print(f"Import failed: {e}")
