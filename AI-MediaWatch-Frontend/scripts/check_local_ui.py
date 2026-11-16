"""Check local dashboard pages in an isolated headless Chrome profile.

Does not start collection or run investigation/inference. Saves screenshots
under data/ui-check and uses the configured local demo login.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import httpx
from dotenv import dotenv_values
from websockets.sync.client import connect


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / "data" / "ui-check"
    output.mkdir(parents=True, exist_ok=True)
    cfg = dotenv_values(root / ".env")
    base = "http://127.0.0.1:5174"
    auth = httpx.post(base + "/api/v1/auth/login", json={
        "email": cfg["AIMW_ADMIN_EMAIL"], "password": cfg["AIMW_ADMIN_PASSWORD"],
    }).json()
    chrome = Path(os.environ["ProgramFiles"]) / "Google/Chrome/Application/chrome.exe"
    process = subprocess.Popen([
        str(chrome), "--headless=new", "--remote-debugging-port=9237",
        "--no-first-run", "--no-default-browser-check",
        "--user-data-dir=" + str(output / ("profile-" + uuid.uuid4().hex)),
        "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(60):
            try:
                page = httpx.put("http://127.0.0.1:9237/json/new?about:blank").json()
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("Chrome debugging endpoint did not start")
        with connect(page["webSocketDebuggerUrl"], max_size=20_000_000) as ws:
            serial = 0
            errors = []
            def command(method, params=None):
                nonlocal serial
                serial += 1
                ws.send(json.dumps({"id": serial, "method": method, "params": params or {}}))
                while True:
                    event = json.loads(ws.recv(timeout=30))
                    if event.get("method") == "Runtime.exceptionThrown":
                        errors.append(event["params"]["exceptionDetails"].get("text"))
                    if event.get("method") == "Runtime.consoleAPICalled" and event["params"]["type"] in ("error", "warning"):
                        errors.append([arg.get("value", arg.get("description")) for arg in event["params"]["args"]])
                    if event.get("id") == serial:
                        if "error" in event:
                            raise RuntimeError(event["error"])
                        return event.get("result", {})
            def evaluate(expression):
                return command("Runtime.evaluate", {"expression": expression,
                    "returnByValue": True, "awaitPromise": True})["result"].get("value")
            command("Page.enable")
            command("Runtime.enable")
            command("Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
            command("Page.navigate", {"url": base})
            time.sleep(1)
            storage = {"aimw_token": auth["access_token"], "aimw_email": auth["email"],
                       "aimw_role": auth["role"], "aimw_dark": "0"}
            evaluate("Object.entries(" + json.dumps(storage) + ").forEach(([k,v])=>localStorage.setItem(k,v))")
            for route in ("/", "/biometrics", "/investigate"):
                command("Page.navigate", {"url": base + route})
                time.sleep(2)
                info = evaluate("JSON.stringify({title:document.querySelector('h1')?.innerText,color:document.querySelector('h1') && getComputedStyle(document.querySelector('h1')).color,text:document.body.innerText})")
                details = json.loads(info)
                assert details["title"], (route, details)
                assert details["color"] == "rgb(17, 24, 39)", (route, details["color"])
                if route == "/":
                    assert "FAILED" in details["text"] and "95/100" in details["text"]
                    assert evaluate("document.querySelectorAll('a a, a button').length") == 0
                if route == "/biometrics":
                    assert "0 reference logos loaded" in details["text"]
                shot = command("Page.captureScreenshot", {"format": "png"})["data"]
                (output / (route.strip("/") or "queue")).with_suffix(".png").write_bytes(base64.b64decode(shot))
                print(route, details["title"], details["color"], "PASS")
            assert not errors, errors
            print("No browser console warnings, errors, or uncaught exceptions")
            command("Browser.close")
    finally:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()


if __name__ == "__main__":
    main()
