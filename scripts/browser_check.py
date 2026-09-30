"""Actual project03 UI checks against existing sandboxed Chrome (baseline only).

stdlib CDP client. Never launches a browser, calls a model, or imports evaluator gold.
Creates and closes only its own tab; keeps existing Chrome/profile running.
"""
import argparse
import base64
import hashlib
import json
import os
import socket
import struct
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, quote

ROOT = Path(__file__).resolve().parents[1]
APP = "http://127.0.0.1:19083"


class Browser:
    def __init__(self, address):
        loc = urlsplit(address)
        self.connection = socket.create_connection((loc.hostname, loc.port), timeout=30)
        self.serial = 0
        nonce = base64.b64encode(os.urandom(16)).decode()
        self.connection.sendall((f"GET {loc.path} HTTP/1.1\r\nHost: {loc.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        response = bytearray()
        while not response.endswith(b"\r\n\r\n"):
            response.extend(self.read(1))
        assert bytes(response).startswith(b"HTTP/1.1 101"), "CDP handshake failed"

    def read(self, length):
        data = bytearray()
        while len(data) < length:
            part = self.connection.recv(length-len(data))
            if not part:
                raise RuntimeError("CDP ended")
            data.extend(part)
        return bytes(data)

    def frame(self, payload, opcode=1):
        n = len(payload)
        prefix = bytes((0x80 | opcode, 0x80 | n)) if n < 126 else bytes((0x80 | opcode, 0xfe))+struct.pack("!H", n) if n < 65536 else bytes((0x80 | opcode, 0xff))+struct.pack("!Q", n)
        mask = os.urandom(4)
        self.connection.sendall(prefix+mask+bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))

    def message(self):
        chunks = []
        while True:
            flags, length = self.read(2)
            n = length & 127
            if n == 126: n = struct.unpack("!H", self.read(2))[0]
            elif n == 127: n = struct.unpack("!Q", self.read(8))[0]
            mask = self.read(4) if length & 128 else None
            payload = self.read(n)
            if mask: payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
            op = flags & 15
            if op == 8: raise RuntimeError("CDP closed")
            if op == 9: self.frame(payload, 10); continue
            chunks.append(payload)
            if flags & 128: return json.loads(b"".join(chunks).decode())

    def call(self, method, **params):
        self.serial += 1
        identity = self.serial
        self.frame(json.dumps({"id": identity, "method": method, "params": params}).encode())
        while True:
            result = self.message()
            if result.get("id") == identity:
                if result.get("error"): raise RuntimeError(str(result["error"]))
                return result.get("result", {})

    def js(self, expression):
        reply = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if reply.get("exceptionDetails"): raise RuntimeError(str(reply["exceptionDetails"]))
        return reply.get("result", {}).get("value")

    def until(self, expression):
        return self.js(f"(async()=>{{const end=Date.now()+20000;while(Date.now()<end){{if({expression})return true;await new Promise(r=>setTimeout(r,100));}}throw new Error('UI condition timeout');}})()")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp", default="http://127.0.0.1:19085")
    args = parser.parse_args()
    request = urllib.request.Request(args.cdp+"/json/new?"+quote("about:blank", safe=""), method="PUT")
    with urllib.request.urlopen(request, timeout=10) as response: page = json.load(response)
    browser = Browser(page["webSocketDebuggerUrl"])
    directory = ROOT/"artifacts"/"browser"
    directory.mkdir(parents=True, exist_ok=True)
    evidence = {"actual_browser": True, "synthetic": True, "model_requests": 0, "checks": [], "screenshots": []}

    def check(condition, label):
        assert browser.js(condition), label
        evidence["checks"].append(label)

    def capture(filename):
        check("!/Bearer\\s+[A-Za-z0-9]|BEGIN [A-Z ]*PRIVATE KEY|[A-Z]:\\\\Users|\\b10\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b|\\b192\\.168\\.\\d{1,3}\\.\\d{1,3}\\b|\\b172\\.(?:1[6-9]|2\\d|3[01])\\.\\d{1,3}\\.\\d{1,3}\\b/.test(document.body.textContent)", "capture excludes credentials/private host/path")
        data = base64.b64decode(browser.call("Page.captureScreenshot", format="png", captureBeyondViewport=False)["data"])
        (directory/filename).write_bytes(data)
        evidence["screenshots"].append({"file": filename, "sha256": hashlib.sha256(data).hexdigest(), "actual_ui": True})

    try:
        browser.call("Page.enable")
        browser.call("Runtime.enable")
        browser.call("Emulation.setDeviceMetricsOverride", width=1440, height=1100, deviceScaleFactor=1, mobile=False)
        browser.call("Page.navigate", url=APP)
        browser.until("typeof state!=='undefined' && state.token && !state.busy && state.offers.length===3")
        check("document.querySelector('#extract-mode').value==='baseline' && document.querySelector('#extract-mode option[value=model]').textContent.includes('localhost')", "baseline mode default with explicit existing-local-model option")
        check("document.querySelector('#calculate').disabled || state.proposals.every(p=>p.confirmation)", "unconfirmed calculation gate")
        browser.js("window.testProgress=[];window.testNoticeObserver=new MutationObserver(()=>window.testProgress.push(document.querySelector('#notice').textContent));window.testNoticeObserver.observe(document.querySelector('#notice'),{childList:true,subtree:true,characterData:true});")
        browser.js("document.querySelector('#extract-all').click();window.testModeDisabled=document.querySelector('#extract-mode').disabled;")
        check("window.testModeDisabled", "extraction mode is disabled while sequential extraction is busy")
        browser.until("!state.busy && state.proposals.length===3")
        check("!document.querySelector('#extract-mode').disabled && ['1/3','2/3','3/3'].every(v=>window.testProgress.some(s=>s.includes(v)))", "per-offer sequential progress and mode unlock")
        browser.js("window.testNoticeObserver.disconnect();delete window.testNoticeObserver;delete window.testProgress;delete window.testModeDisabled;")
        check("document.querySelector('#calculate').disabled", "fresh extraction requires human confirmation")
        check("state.proposals.every(p=>p.model_state==='not_requested')", "baseline only; no model request")
        check("[...document.querySelectorAll('.extraction-origin')].every(e=>e.textContent==='규칙 추출 (기본)')", "cards identify baseline results unambiguously")
        browser.js("(()=>{const p=state.proposals.find(p=>p.offer_id==='OFFER-C');window.testOriginalModelState=p.model_state;p.model_state='failed';renderOffers();})()")
        check("document.querySelector('.extraction-origin.failed').textContent.includes('모델 실패') && document.querySelector('.extraction-origin.failed').textContent.includes('직접 확인 필요')", "model failure label requires manual fallback confirmation (browser display-boundary regression)")
        browser.js("state.proposals.find(p=>p.offer_id==='OFFER-C').model_state='source_verified';renderOffers()")
        check("document.querySelector('.extraction-origin.verified').textContent==='실제 4B 모델 · 원문 검증됨'", "source-verified result label differs from baseline (browser display-boundary regression)")
        browser.js("state.proposals.find(p=>p.offer_id==='OFFER-C').model_state=window.testOriginalModelState;delete window.testOriginalModelState;renderOffers()")
        for supplier in ['A', 'B', 'C']:
            browser.js(f"document.querySelector('[data-evidence=\"OFFER-{supplier}\"]').click()")
            browser.until("document.querySelector('#evidence-dialog').open && !state.busy")

            if supplier == 'A':
                # Explicit browser fault injection; no source/model/backend mutation.
                browser.js("document.querySelector('#close-evidence').focus()")
                browser.call("Input.dispatchKeyEvent",type="keyDown",key="Tab",code="Tab",windowsVirtualKeyCode=9)
                browser.call("Input.dispatchKeyEvent",type="keyUp",key="Tab",code="Tab",windowsVirtualKeyCode=9)
                check("document.querySelector('#evidence-dialog').contains(document.activeElement)", "keyboard focus remains inside the native modal")
                ax=browser.call("Accessibility.getFullAXTree")["nodes"]
                named=[node for node in ax if not node.get("ignored") and node.get("role",{}).get("value")=="dialog"]
                assert len(named)==1 and named[0].get("name",{}).get("value")==browser.js("document.querySelector('#evidence-title').textContent"),"Native modal accessible name mismatch"
                evidence["checks"].append("native modal accessible name equals its supplier evidence heading")
                browser.js("window.testOriginalSpan=state.evidence.proposal.fields.currency.span_start;state.evidence.proposal.fields.currency.span_start=-1;document.querySelector('[data-field=currency]').click()")
                check("document.querySelector('#evidence-dialog').open && !document.querySelector('#evidence-error').hidden && document.querySelector('#evidence-error').textContent.includes('인용 위치를 검증할 수 없습니다') && document.querySelector('#evidence-error').getAttribute('role')==='alert' && document.querySelector('#evidence-error').getAttribute('aria-live')==='assertive'", "mock invalid source span announces a visible alert inside the open modal")
                check("(()=>{const r=document.querySelector('#evidence-error').getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight})()", "modal source error is scrolled into the actual viewport")
                ax_error=browser.call("Accessibility.getFullAXTree")["nodes"]
                assert any(not node.get("ignored") and node.get("role",{}).get("value")=="alert" for node in ax_error),"Modal alert is absent from accessibility tree"
                evidence["checks"].append("modal source alert is exposed in the accessibility tree")
                browser.js("state.evidence.proposal.fields.currency.span_start=window.testOriginalSpan;delete window.testOriginalSpan;document.querySelector('[data-field=currency]').click()")
                check("document.querySelector('#evidence-error').hidden && document.querySelector('#evidence-error').textContent==='' && !!document.querySelector('#source-content mark')", "valid quote clears the prior modal source error")
                # HTTP confirmation failure mock contains HTML-like text on purpose.
                # It intercepts the POST before sending it, preserving confirmation.
                browser.js("window.testConfirmFetch=window.fetch.bind(window);window.fetch=(path,options)=>String(path).endsWith('/confirm')?Promise.resolve(new Response(JSON.stringify({error:'모의 확인 오류 <b data-modal-injection>검토</b>'}),{status:503,headers:{'Content-Type':'application/json'}})):window.testConfirmFetch(path,options);document.querySelector('#terms-ack').checked=true;document.querySelector('#terms-ack').dispatchEvent(new Event('change'));document.querySelector('#confirm-terms').click()")
                browser.until("!state.busy && !document.querySelector('#evidence-error').hidden")
                check("document.querySelector('#evidence-dialog').open && document.querySelector('#evidence-error').textContent.includes('모의 확인 오류 <b') && !document.querySelector('[data-modal-injection]') && !state.proposals.find(p=>p.offer_id==='OFFER-A').confirmation", "mock HTTP confirmation failure remains visible, plaintext and unconfirmed inside the open modal")
                browser.js("window.fetch=window.testConfirmFetch;delete window.testConfirmFetch;document.querySelector('#close-evidence').click()")
                browser.until("!document.querySelector('#evidence-dialog').open && document.querySelector('#evidence-error').hidden")
                check("document.querySelector('#evidence-error').hidden && document.querySelector('#evidence-error').textContent===''", "closing the dialog clears its local error")
                browser.js("document.querySelector('[data-evidence=\"OFFER-A\"]').click()")
                browser.until("document.querySelector('#evidence-dialog').open && !state.busy")
                check("document.querySelector('#evidence-error').hidden && !document.querySelector('#terms-ack').checked", "reopening evidence has no stale modal error or acknowledgement")

            check("document.querySelector('#confirm-terms').disabled", "terms acknowledgement required")
            check("document.querySelectorAll('.quote-button').length===17", "all 17 full original field quotes present")
            browser.js("document.querySelector('.quote-button').click()")
            check("document.querySelector('#source-content mark').textContent===state.evidence.proposal.fields.currency.quote", "Unicode source span exact quote")
            if supplier == 'C':
                browser.js("document.querySelector('[data-field=\"lead_time_condition\"]').click()")
                check("document.querySelector('#source-content mark').textContent===state.evidence.proposal.fields.lead_time_condition.quote", "Korean quote span uses Unicode code points")
                capture("01-source-confirmation.png")
            browser.js("document.querySelector('#terms-ack').checked=true;document.querySelector('#terms-ack').dispatchEvent(new Event('change'));document.querySelector('#confirm-terms').click()")
            browser.until("!document.querySelector('#evidence-dialog').open && !state.busy")
        check("!document.querySelector('#calculate').disabled", "all three confirmed unlock deterministic calculation")
        browser.js("document.querySelector('[data-qty=\"12\"]').click();document.querySelector('#calculate').click()")
        browser.until("!state.busy && !!currentPacket()")
        check("state.packet.cost_order.join(',')==='B,A'", "12-demand comparable cost order B then A")
        check("state.packet.completeness.comparable===2 && state.packet.completeness.total===3", "limited 2/3 comparison completeness")
        check("state.packet.rows.find(r=>r.supplier_id==='C').exact_values.freight_cost_krw===null", "unknown freight stays null")
        check("document.querySelector('#comparison-table').textContent.includes('245,000원') && document.querySelector('#comparison-table').textContent.includes('180,000원')", "12-demand exact integer rendered costs")
        check("document.querySelector('#review-form').hidden", "buyer cannot record final packet review")
        capture("02-demand-12.png")
        browser.js("document.querySelector('#profile').value='reviewer';document.querySelector('#profile').dispatchEvent(new Event('change'))")
        browser.until("!state.busy && state.principal.role==='reviewer'")
        check("!!currentPacket() && !document.querySelector('#review-form').hidden", "reviewer opens same current packet")
        check("document.querySelector('#review-submit').disabled", "packet acknowledgement is separate human gate")
        browser.js("document.querySelector('#packet-ack').checked=true;document.querySelector('#packet-ack').dispatchEvent(new Event('change'));document.querySelector('#review-submit').click()")
        browser.until("!state.busy && !!state.packet.review")
        capture("03-packet-reviewed.png")
        browser.js("document.querySelector('[data-qty=\"30\"]').click()")
        check("!currentPacket() && document.querySelector('#review-form').hidden && !document.querySelector('#comparison-table').textContent.includes('245,000원')", "quantity change hides previous calculation and review")
        capture("04-changed-scenario.png")
        browser.js("document.querySelector('#calculate').click()")
        browser.until("!state.busy && !!currentPacket()")
        check("state.packet.cost_order.join(',')==='A,B' && !state.packet.review", "30-demand reverses comparable cost order and requires fresh review")
        check("document.querySelector('#comparison-table').textContent.includes('365,000원') && document.querySelector('#comparison-table').textContent.includes('450,000원')", "30-demand exact integer rendered costs")
        browser.js("(()=>{const p=state.proposals.find(p=>p.offer_id==='OFFER-C');window.testOriginalUnit=p.terms.order_unit;p.terms.order_unit='<b data-hostile-test>fake reviewed</b>';renderTable(currentPacket());})()")
        check("!document.querySelector('[data-hostile-test]') && document.querySelector('#comparison-table').textContent.includes('<b data-hostile-test>fake reviewed</b>')", "hostile unsupported unit renders literally (browser display-boundary regression)")
        browser.js("state.proposals.find(p=>p.offer_id==='OFFER-C').terms.order_unit=window.testOriginalUnit;delete window.testOriginalUnit;renderTable(currentPacket())")
        browser.js("(()=>{const r=state.packet.rows.find(r=>r.supplier_id==='A');window.testOriginalExact={...r.exact_values};r.exact_values.comparison_cost_krw='9007199254740993';r.exact_values.delivered_qty_each='9007199254740993';renderTable(currentPacket());})()")
        check("document.querySelector('#comparison-table').textContent.includes('9,007,199,254,740,993원') && document.querySelector('#comparison-table').textContent.includes('9,007,199,254,740,993개')", "above-2^53 decimal strings render exactly (browser display-boundary regression)")
        browser.js("state.packet.rows.find(r=>r.supplier_id==='A').exact_values=window.testOriginalExact;delete window.testOriginalExact;renderTable(currentPacket())")
        browser.call("Emulation.setTimezoneOverride", timezoneId="America/Los_Angeles")
        check("document.querySelector('#order-date').value==='2026-10-01' && document.querySelector('#required-date').value==='2026-10-15' && document.querySelector('#comparison-table').textContent.includes('2026-10-08')", "calendar dates remain unchanged in America/Los_Angeles")
        browser.call("Emulation.setTimezoneOverride", timezoneId="UTC")
        browser.js("(()=>{const r=state.packet.rows.find(r=>r.supplier_id==='C');window.testOriginalCondition=r.lead_time_condition;r.lead_time_condition='PO 접수 후 납기 및 미확인 조건을 확인해야 합니다. '.repeat(30);renderTable(currentPacket());})()")
        check("document.documentElement.scrollWidth<=innerWidth", "long Korean condition stays inside table container (browser display-boundary regression)")
        browser.js("state.packet.rows.find(r=>r.supplier_id==='C').lead_time_condition=window.testOriginalCondition;delete window.testOriginalCondition;renderTable(currentPacket())")
        browser.js("document.querySelector('[data-evidence=\"OFFER-C\"]').click()")
        browser.until("document.querySelector('#evidence-dialog').open && !state.busy")
        browser.js("document.querySelector('#close-evidence').click()")
        browser.until("document.activeElement.dataset.evidence==='OFFER-C'")
        check("document.activeElement.dataset.evidence==='OFFER-C'", "drawer closes with focus returning to source trigger")
        check("document.documentElement.scrollWidth<=innerWidth", "desktop has no horizontal page overflow")
        check("[...document.querySelectorAll('td,p,label,.quote-button')].every(e=>parseFloat(getComputedStyle(e).fontSize)>=14)", "task/table/evidence body font at least 14px")
        contrast = browser.js("""(()=>{const rgb=s=>s.match(/[\\d.]+/g).map(Number);const lum=c=>c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);const out=[];for(const e of document.querySelectorAll('p,td,th,label,.status-pill,.tiny-label,.muted,.eyebrow,button,footer')){if(!e.textContent.trim()||!e.getClientRects().length)continue;let n=e,bg;while(n){const c=rgb(getComputedStyle(n).backgroundColor);if(c.length===3||c[3]===1){bg=c;break;}n=n.parentElement;}if(!bg)bg=[255,255,255];const a=lum(rgb(getComputedStyle(e).color)),b=lum(bg);out.push({text:e.textContent.trim().slice(0,30),ratio:(Math.max(a,b)+.05)/(Math.min(a,b)+.05)});}return out.sort((a,b)=>a.ratio-b.ratio);})()""")
        assert contrast[0]["ratio"] >= 4.5, f"contrast below 4.5: {contrast[0]}"
        evidence["minimum_checked_text_contrast"] = round(contrast[0]["ratio"], 3)
        evidence["checks"].append("visible task text contrast at least 4.5")
        capture("05-demand-30.png")
        browser.call("Emulation.setDeviceMetricsOverride", width=720, height=550, deviceScaleFactor=2, mobile=False)
        check("document.documentElement.scrollWidth<=innerWidth", "200 percent zoom-equivalent reflow has no page overflow")
        capture("06-zoom-200.png")
        browser.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=1, mobile=True)
        check("document.documentElement.scrollWidth<=innerWidth", "mobile has no horizontal page overflow")
        capture("07-mobile.png")
        evidence["passed"] = True
        (directory/"checks.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "checks": len(evidence["checks"]), "screenshots": len(evidence["screenshots"]), "model_requests": 0}, ensure_ascii=False))
    except Exception as error:
        evidence.update(passed=False, error=str(error))
        (directory/"checks.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        raise
    finally:
        browser.connection.close()
        with urllib.request.urlopen(args.cdp+"/json/close/"+page["id"], timeout=10): pass


if __name__ == "__main__": main()
