#!/usr/bin/env python3
"""
ESP32 Network Diagnostic Tool
Run this script to test connectivity to your ESP32 before running zone.py
"""

import requests
import socket
import time
import subprocess
import sys

ESP32_IP = "10.148.248.88"
ESP32_PORT = 80

def test_ping():
    """Test basic network connectivity using ping"""
    print(f"🏓 Testing ping to {ESP32_IP}...")
    try:
        # Windows ping command
        result = subprocess.run(['ping', '-n', '4', ESP32_IP], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ Ping successful!")
            return True
        else:
            print("❌ Ping failed!")
            print(result.stdout)
            return False
    except Exception as e:
        print(f"❌ Ping test error: {e}")
        return False

def test_tcp_connection():
    """Test TCP connection to ESP32 port 80"""
    print(f"🔌 Testing TCP connection to {ESP32_IP}:{ESP32_PORT}...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((ESP32_IP, ESP32_PORT))
        sock.close()
        
        if result == 0:
            print("✅ TCP connection successful!")
            return True
        else:
            print("❌ TCP connection failed!")
            return False
    except Exception as e:
        print(f"❌ TCP connection error: {e}")
        return False

def test_http_request():
    """Test HTTP request to ESP32"""
    print(f"🌐 Testing HTTP request to {ESP32_IP}...")
    
    # Test different timeouts
    timeouts = [1, 3, 5, 10]
    
    for timeout in timeouts:
        try:
            print(f"   Trying with {timeout}s timeout...")
            response = requests.get(f"http://{ESP32_IP}/", timeout=timeout)
            print(f"✅ HTTP request successful with {timeout}s timeout!")
            print(f"   Status Code: {response.status_code}")
            print(f"   Response Time: {response.elapsed.total_seconds():.2f}s")
            return True, timeout
        except requests.exceptions.Timeout:
            print(f"   ⏰ Timeout with {timeout}s")
        except requests.exceptions.ConnectionError:
            print(f"   🔌 Connection error with {timeout}s")
        except Exception as e:
            print(f"   ❌ Error with {timeout}s: {e}")
    
    print("❌ All HTTP requests failed!")
    return False, None

def test_esp32_endpoints():
    """Test specific ESP32 endpoints"""
    endpoints = [
        "/",
        "/light?zone=1&state=OFF",  # Safe command
        "/calibrate"
    ]
    
    print(f"🎯 Testing ESP32 endpoints...")
    for endpoint in endpoints:
        try:
            url = f"http://{ESP32_IP}{endpoint}"
            print(f"   Testing: {endpoint}")
            response = requests.get(url, timeout=5)
            print(f"   ✅ {endpoint} -> HTTP {response.status_code}")
        except requests.exceptions.Timeout:
            print(f"   ⏰ {endpoint} -> Timeout")
        except Exception as e:
            print(f"   ❌ {endpoint} -> Error: {str(e)[:50]}")

def main():
    print("🔧 ESP32 Network Diagnostic Tool")
    print("=" * 40)
    
    # Run all tests
    ping_ok = test_ping()
    print()
    
    tcp_ok = test_tcp_connection()
    print()
    
    http_ok, best_timeout = test_http_request()
    print()
    
    if http_ok:
        test_esp32_endpoints()
        print()
    
    # Summary
    print("📊 DIAGNOSTIC SUMMARY:")
    print("=" * 40)
    print(f"Ping Test:       {'✅ PASS' if ping_ok else '❌ FAIL'}")
    print(f"TCP Connection:  {'✅ PASS' if tcp_ok else '❌ FAIL'}")
    print(f"HTTP Request:    {'✅ PASS' if http_ok else '❌ FAIL'}")
    
    if http_ok:
        print(f"Best Timeout:    {best_timeout} seconds")
        print(f"\n💡 Recommendation: Use timeout={best_timeout} in your zone.py script")
    
    if not ping_ok:
        print(f"\n🔧 TROUBLESHOOTING STEPS:")
        print(f"1. Check if ESP32 is powered on")
        print(f"2. Verify ESP32 IP address: {ESP32_IP}")
        print(f"3. Ensure both devices are on same WiFi network")
        print(f"4. Check WiFi signal strength")
    
    if ping_ok and not tcp_ok:
        print(f"\n🔧 TROUBLESHOOTING STEPS:")
        print(f"1. ESP32 web server might not be running")
        print(f"2. Port 80 might be blocked")
        print(f"3. Check ESP32 Serial Monitor for errors")
    
    if tcp_ok and not http_ok:
        print(f"\n🔧 TROUBLESHOOTING STEPS:")
        print(f"1. ESP32 might be overloaded")
        print(f"2. Increase timeout in your Python script")
        print(f"3. Add delay between requests")

if __name__ == "__main__":
    main()