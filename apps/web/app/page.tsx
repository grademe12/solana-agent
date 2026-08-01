"use client";

import { ChangeEvent, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_AGENT_API_URL ?? "http://127.0.0.1:8000";
const USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU";
const SAMPLE_PAYLOAD =
  "solana:FvJ8k8HhXp4a3zQyFMZd4FvEqcYdYE7gSZWxrEBRfBsB?amount=0.10" +
  `&spl-token=${USDC_MINT}&reference=SysvarC1ock11111111111111111111111111111111` +
  "&label=Demo%20Merchant&message=Order%20P0-001";

type Intent = {
  intent_id: string;
  confidence: string;
  network: string;
  recipient: string | null;
  amount: { atomic: string; decimals: number } | null;
  amount_display: string | null;
  asset: { symbol: string; mint: string | null; decimals: number } | null;
  reference: string | null;
  label: string | null;
  rejection_code: string | null;
  rejection_reason: string | null;
};

type CheckoutResult = {
  status: string;
  mode?: string;
  submitted?: boolean;
  real_funds_moved?: boolean;
  duplicate?: boolean;
  intent_id?: string;
  failure_code?: string | null;
  policy_rejection_codes?: string[];
  receipt?: {
    mock: boolean;
    signature: string;
    network: string;
    recipient: string;
    mint: string;
    amount_atomic: string;
    decimals: number;
    reference: string;
    explorer_url: string | null;
  } | null;
};

type AgentRunResponse = {
  final_text: string;
  trajectory: { tool_name: string; phase: string }[];
  checkout_result: CheckoutResult | null;
};

function amountToAtomic(value: string): number {
  if (!/^\d+(\.\d{0,6})?$/.test(value)) {
    throw new Error("USDC 금액은 소수점 6자리 이내로 입력하세요.");
  }
  const [whole, fraction = ""] = value.split(".");
  const atomic = BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0"));
  if (atomic > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error("정책 금액이 허용 범위를 초과했습니다.");
  }
  return Number(atomic);
}

async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json()) as T & { detail?: unknown };
  if (!response.ok) {
    const detail = "detail" in body ? JSON.stringify(body.detail) : response.statusText;
    throw new Error(detail || "요청을 처리하지 못했습니다.");
  }
  return body;
}

function shorten(value: string | null | undefined, size = 8) {
  if (!value) return "—";
  if (value.length <= size * 2 + 3) return value;
  return `${value.slice(0, size)}…${value.slice(-size)}`;
}

export default function Home() {
  const [payload, setPayload] = useState(SAMPLE_PAYLOAD);
  const [intent, setIntent] = useState<Intent | null>(null);
  const [perTransaction, setPerTransaction] = useState("1.00");
  const [dailyLimit, setDailyLimit] = useState("5.00");
  const [transactionCount, setTransactionCount] = useState("10");
  const [result, setResult] = useState<CheckoutResult | null>(null);
  const [agentTrajectory, setAgentTrajectory] = useState<AgentRunResponse["trajectory"]>([]);
  const [agentText, setAgentText] = useState("");
  const [busy, setBusy] = useState<"decode" | "inspect" | "execute" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canExecute = intent?.confidence === "authoritative" && busy === null;
  const statusTone = useMemo(() => {
    if (!result) return "idle";
    if (result.status === "confirmed") return "success";
    if (result.status === "rejected" || result.status === "failed") return "danger";
    return "pending";
  }, [result]);

  async function inspect(nextPayload = payload) {
    setBusy("inspect");
    setError(null);
    setResult(null);
    setAgentTrajectory([]);
    setAgentText("");
    try {
      const response = await fetch(`${API_URL}/api/intents/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload: nextPayload }),
      });
      setIntent(await readJson<Intent>(response));
    } catch (caught) {
      setIntent(null);
      setError(caught instanceof Error ? caught.message : "결제 요청 분석에 실패했습니다.");
    } finally {
      setBusy(null);
    }
  }

  async function uploadQr(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy("decode");
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch(`${API_URL}/api/qr/decode`, { method: "POST", body: form });
      const decoded = await readJson<{ raw_payload: string }>(response);
      setPayload(decoded.raw_payload);
      await inspect(decoded.raw_payload);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "QR 디코딩에 실패했습니다.");
    } finally {
      setBusy(null);
      event.target.value = "";
    }
  }

  async function authorizeAndExecute() {
    if (!intent || intent.confidence !== "authoritative") return;
    setBusy("execute");
    setError(null);
    setResult(null);
    setAgentTrajectory([]);
    setAgentText("");
    try {
      const sessionId = crypto.randomUUID();
      const policy = {
        policy_id: `web-${sessionId}`,
        user_id: "demo-user",
        enabled: true,
        allowed_networks: ["solana:devnet"],
        allowed_asset_mints: [USDC_MINT],
        allowed_merchants: ["demo-merchant"],
        budget_asset_mint: USDC_MINT,
        budget_decimals: 6,
        max_per_transaction_atomic: amountToAtomic(perTransaction),
        max_daily_atomic: amountToAtomic(dailyLimit),
        max_transactions_per_day: Number.parseInt(transactionCount, 10),
        max_network_fee_lamports: 100_000,
        max_slippage_bps: 0,
        expires_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(),
      };
      const authorizationResponse = await fetch(`${API_URL}/api/authorizations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, payment_payload: payload, policy }),
      });
      const authorization = await readJson<{ authorization_id: string }>(authorizationResponse);
      const prompt = [
        "제공한 authorization에 바인딩된 결제 요청을 먼저 분석한 뒤 결제를 실행해줘.",
        "결과는 도구 응답에 근거해서만 설명해.",
        `authorization_id: ${authorization.authorization_id}`,
      ].join("\n");
      const executeResponse = await fetch(`${API_URL}/api/agent/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: "demo-user", session_id: sessionId, prompt }),
      });
      const agentRun = await readJson<AgentRunResponse>(executeResponse);
      setAgentTrajectory(agentRun.trajectory);
      setAgentText(agentRun.final_text);
      if (!agentRun.checkout_result) {
        throw new Error("Gemini가 결제 실행 도구를 호출하지 않았습니다.");
      }
      setResult(agentRun.checkout_result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "결제를 실행하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main>
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Agentic Checkout 홈">
          <span className="brand-mark">A</span>
          <span>Agentic Checkout</span>
        </a>
        <div className="network-pill"><span /> Solana Devnet</div>
      </header>

      <section className="hero" id="top">
        <div>
          <div className="eyebrow">Policy-guarded stablecoin payments</div>
          <h1>QR 하나를<br />검증 가능한 결제로.</h1>
        </div>
        <p>
          결제 요청을 해석하고, 사용자가 정한 한도 안에서만 실행합니다.
          네트워크·토큰·수취인·reference는 서명 전후에 다시 검증됩니다.
        </p>
      </section>

      <section className="workspace" aria-label="결제 데모">
        <div className="panel request-panel">
          <div className="panel-heading">
            <span className="step">01</span>
            <div><h2>결제 요청</h2><p>QR 이미지 또는 Solana Pay URI</p></div>
          </div>

          <label className="upload-zone">
            <input type="file" accept="image/png,image/jpeg,image/webp" onChange={uploadQr} />
            <span className="upload-icon">＋</span>
            <strong>{busy === "decode" ? "QR을 읽는 중…" : "QR 이미지 업로드"}</strong>
            <small>PNG, JPG, WEBP · 최대 10MB</small>
          </label>

          <div className="divider"><span>또는 URI 직접 입력</span></div>
          <label className="field">
            <span>Payment payload</span>
            <textarea value={payload} onChange={(event) => setPayload(event.target.value)} rows={6} />
          </label>
          <button className="secondary-button" onClick={() => inspect()} disabled={busy !== null}>
            {busy === "inspect" ? "분석 중…" : "요청 분석"}
          </button>

          {intent && (
            <div className={`intent-card ${intent.confidence}`}>
              <div className="intent-title">
                <span>{intent.confidence === "authoritative" ? "검증 가능한 요청" : "실행 불가"}</span>
                <b>{intent.confidence}</b>
              </div>
              <dl>
                <div><dt>금액</dt><dd>{intent.amount_display ?? "—"} {intent.asset?.symbol ?? ""}</dd></div>
                <div><dt>네트워크</dt><dd>{intent.network}</dd></div>
                <div><dt>수취인</dt><dd title={intent.recipient ?? ""}>{shorten(intent.recipient)}</dd></div>
                <div><dt>Reference</dt><dd title={intent.reference ?? ""}>{shorten(intent.reference)}</dd></div>
              </dl>
              {intent.rejection_reason && <p className="rejection">{intent.rejection_reason}</p>}
            </div>
          )}
        </div>

        <div className="panel policy-panel">
          <div className="panel-heading">
            <span className="step">02</span>
            <div><h2>지출 정책</h2><p>승인을 대신하는 결정론적 한도</p></div>
          </div>
          <div className="policy-grid">
            <label className="field"><span>거래당 최대</span><div className="amount-input"><input value={perTransaction} onChange={(e) => setPerTransaction(e.target.value)} inputMode="decimal" /><b>USDC</b></div></label>
            <label className="field"><span>24시간 최대</span><div className="amount-input"><input value={dailyLimit} onChange={(e) => setDailyLimit(e.target.value)} inputMode="decimal" /><b>USDC</b></div></label>
            <label className="field full"><span>최대 거래 횟수</span><div className="amount-input"><input value={transactionCount} onChange={(e) => setTransactionCount(e.target.value)} inputMode="numeric" /><b>회</b></div></label>
          </div>
          <ul className="guard-list">
            <li><span>✓</span> Solana Devnet만 허용</li>
            <li><span>✓</span> Circle Devnet USDC mint 고정</li>
            <li><span>✓</span> 등록된 Demo Merchant만 허용</li>
            <li><span>✓</span> 중복 intent 자동 차단</li>
          </ul>
          <button className="primary-button" onClick={authorizeAndExecute} disabled={!canExecute}>
            {busy === "execute" ? "정책 검증 및 실행 중…" : "정책 승인 후 결제 실행"}
          </button>
          <p className="consent-copy">버튼을 누르면 위 정책이 24시간 authorization으로 저장됩니다.</p>
        </div>
      </section>

      {(result || error) && (
        <section className={`result-panel ${statusTone}`} aria-live="polite">
          <div className="result-heading">
            <div>
              <span className="step">03</span>
              <h2>{error ? "실행 오류" : result?.status === "confirmed" ? "결제 완료" : "실행 결과"}</h2>
            </div>
            {result && <span className="mode-badge">{result.mode ?? "guarded"}</span>}
          </div>
          {error ? <p className="error-message">{error}</p> : result && (
            <>
              {agentTrajectory.length > 0 && (
                <div className="agent-evidence">
                  <div>
                    <span>Gemini / ADK tool trajectory</span>
                    <div className="tool-chips">
                      {agentTrajectory.map((trace, index) => (
                        <code key={`${trace.tool_name}-${trace.phase}-${index}`}>
                          {trace.tool_name} · {trace.phase}
                        </code>
                      ))}
                    </div>
                  </div>
                  {agentText && <p>{agentText}</p>}
                </div>
              )}
              <div className="timeline">
                <div className="done"><span>1</span><b>Intent 분석</b><small>{shorten(result.intent_id)}</small></div>
                <div className="done"><span>2</span><b>정책 검증</b><small>{result.policy_rejection_codes?.length ? "거부" : "통과"}</small></div>
                <div className={result.submitted ? "done" : "stopped"}><span>3</span><b>거래 제출</b><small>{result.submitted ? "완료" : "중단"}</small></div>
                <div className={result.status === "confirmed" ? "done" : "stopped"}><span>4</span><b>온체인 검증</b><small>{result.status}</small></div>
              </div>
              {result.failure_code && <p className="error-message">{result.failure_code}</p>}
              {result.receipt && (
                <div className="receipt-card">
                  <div><span>Signature</span><code>{shorten(result.receipt.signature, 12)}</code></div>
                  <div><span>Amount</span><strong>{Number(result.receipt.amount_atomic) / 10 ** result.receipt.decimals} USDC</strong></div>
                  <div><span>Reference</span><code>{shorten(result.receipt.reference, 10)}</code></div>
                  <div><span>Proof</span>{result.receipt.explorer_url ? <a href={result.receipt.explorer_url} target="_blank" rel="noreferrer">Explorer에서 확인 ↗</a> : <em>Mock receipt</em>}</div>
                </div>
              )}
            </>
          )}
        </section>
      )}

      <footer><span>Gemini · Google ADK · Solana</span><span>Policy before signature. Proof after settlement.</span></footer>
    </main>
  );
}
