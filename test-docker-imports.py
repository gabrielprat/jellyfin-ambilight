#!/usr/bin/env python3
"""
Docker Import Test
==================

Test script to verify all imports work correctly for the Docker container.
Run this before starting the Docker container to ensure everything is set up properly.
"""

import sys
import os

# Simulate Docker environment
sys.path.append('/app')
os.environ['JELLYFIN_API_KEY'] = 'test'
os.environ['JELLYFIN_BASE_URL'] = 'http://test'
os.environ['AMBILIGHT_DATA_DIR'] = '/tmp/test_docker'

def test_storage_import():
    """Test file-based storage import"""
    print("📁 Testing storage import...")
    try:
        from storage import FileBasedStorage
        storage = FileBasedStorage('/tmp/test_docker')
        print("✅ Storage imported and initialized successfully")
        return True
    except ImportError:
        try:
            from storage_file_based import FileBasedStorage
            storage = FileBasedStorage('/tmp/test_docker')
            print("✅ Storage imported from fallback and initialized successfully")
            return True
        except Exception as e:
            print(f"❌ Storage import failed: {e}")
            return False
    except Exception as e:
        print(f"❌ Storage initialization failed: {e}")
        return False

def test_extractor_import():
    """Test frame extractor import"""
    print("🎬 Testing frame extractor import...")
    try:
        # Method 1: Direct import
        try:
            from frame_extractor_files import extract_frames_simple_files
            print("✅ Frame extractor imported directly")
            return True
        except ImportError:
            # Method 2: Dynamic import
            import importlib.util
            spec = importlib.util.spec_from_file_location("frame_extractor_files", "./frame-extractor-files.py")
            frame_extractor_files = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(frame_extractor_files)
            extract_frames_simple_files = frame_extractor_files.extract_frames_simple_files
            print("✅ Frame extractor imported dynamically")
            return True
    except Exception as e:
        print(f"❌ Frame extractor import failed: {e}")
        return False

def test_daemon_structure():
    """Test daemon file structure"""
    print("🤖 Testing daemon structure...")
    try:
        daemon_file = "ambilight-daemon-files.py"
        if os.path.exists(daemon_file):
            with open(daemon_file, 'r') as f:
                content = f.read()

            checks = [
                ("storage import", "from storage import FileBasedStorage" in content),
                ("fallback import", "from storage_file_based import FileBasedStorage" in content),
                ("dynamic function", "get_extract_frames_function" in content),
                ("extract usage", "extract_frames_func = get_extract_frames_function()" in content)
            ]

            all_good = True
            for check_name, result in checks:
                if result:
                    print(f"✅ {check_name} found")
                else:
                    print(f"❌ {check_name} missing")
                    all_good = False

            return all_good
        else:
            print(f"❌ Daemon file {daemon_file} not found")
            return False
    except Exception as e:
        print(f"❌ Daemon structure check failed: {e}")
        return False

def main():
    print("🐳 DOCKER IMPORT VERIFICATION")
    print("=" * 50)
    print()

    tests = [
        ("Storage Import", test_storage_import),
        ("Extractor Import", test_extractor_import),
        ("Daemon Structure", test_daemon_structure)
    ]

    all_passed = True
    for test_name, test_func in tests:
        result = test_func()
        if not result:
            all_passed = False
        print()

    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Docker container should start successfully")
        print("🚀 Ready to run: docker-compose up -d")
    else:
        print("❌ SOME TESTS FAILED!")
        print("⚠️  Docker container may have import issues")
        print("🔧 Please check the failed imports above")

    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
