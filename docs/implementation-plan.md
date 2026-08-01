# Agentic Checkout 구현 계획

- 문서 상태: 구현 기준안
- 작성일: 2026-08-01 KST
- 제출 마감: 2026-08-03 23:59 KST
- 목표 트랙: A. Agent-Initiated Commerce / B. Autonomous On-chain Settlement

## 1. 제품 정의

### 한 문장 정의

사용자가 QR 또는 결제 링크와 예산 정책을 전달하면, Gemini 기반 에이전트가 결제 조건을 해석하고 안전성을 검증한 뒤 Solana 스테이블코인 결제를 실행하고 온체인 영수증을 반환한다.

### 해결하려는 문제

현재 스테이블코인 결제에서는 사용자가 지갑, 네트워크, 토큰, 가스비, 수취 주소와 결제 세션을 직접 이해해야 한다. 결제 QR도 형식에 따라 단순 주소, Solana Pay 요청, WalletConnect 연결, Base Pay 세션 또는 일반 URL일 수 있다.

Agentic Checkout은 이를 공통 `PaymentIntent`로 정규화하고, 사람이 매 단계 승인하는 대신 사전에 정의한 정책으로 승인 여부를 결정한다.

### 핵심 원칙

1. Gemini는 결제 흐름을 조율하지만 금액 안전성을 결정하지 않는다.
2. 정책 검증은 일반 코드로 구현하며 결제 실행 함수 내부에서 강제한다.
3. QR과 판매자 응답은 신뢰하지 않는 외부 입력으로 취급한다.
4. 지원하지 않는 네트워크·프로토콜은 추측하여 결제하지 않는다.
5. 트랜잭션 성공이 아니라 결제 의도와 일치하는 온체인 결과까지 검증한다.

## 2. 제출 범위

### P0: 반드시 완성할 범위

- Gemini + Google ADK 단일 결제 에이전트
- QR 이미지 업로드 및 문자열 디코딩
- Solana Pay transfer request 파싱
- Base Pay 등 비-Solana QR 분류 및 안전한 거부
- 결제 의도의 공통 스키마 변환
- 거래당 한도, 일일 한도, 허용 네트워크·토큰·판매자 정책
- 에이전트 전용 Solana 지갑
- Solana Devnet에서 USDC 직접 결제
- 수취인·금액·토큰·reference 기반 결제 검증
- 트랜잭션 서명과 Explorer 링크 반환
- 간단한 웹 데모
- 로컬 실행, 테스트, Cloud Run 배포 가이드

### P1: P0 완료 후 추가할 범위

- x402/pay.sh 결제 URL 어댑터
- 402 결제 조건 분석, 정책 검증, 결제 증명과 함께 재요청
- Firestore 기반 예산 예약·차감 및 중복 결제 방지
- Cloud Logging에 도구 실행·거부 사유·트랜잭션 기록
- 메인넷 극소액 USDC 결제 데모

### P2: 시간 여유가 있을 때만 추가

- Jupiter를 이용한 Solana Mainnet USDT 또는 SOL → USDC 교환
- 최대 슬리피지 및 최소 수령량 검증
- 스왑 후 결제 재개
- Solana Allowance 기반 온체인 위임 한도
- A2A/MCP 외부 호출 인터페이스

### 명시적으로 제외하는 범위

- Base·Ethereum·Tron에서 Solana로 브리징
- 모든 QR 형식의 범용 지원
- 주소만 보고 EVM 네트워크를 추측하는 기능
- Venice 또는 Coinbase 결제 화면을 브라우저 자동화로 조작
- 사용자 기기에 설치된 모든 지갑 자동 탐색
- 법정화폐 온램프·오프램프
- 자체 Solana 프로그램 개발
- 멀티에이전트 협상

## 3. 성공 기준

아래 조건을 모두 만족해야 P0를 완료로 본다.

1. 사용자가 샘플 Solana Pay QR과 예산 정책을 입력할 수 있다.
2. Gemini/ADK가 QR 분석, 잔액 확인, 결제 실행 도구를 실제로 선택한다.
3. 실행 직전에 결정론적 정책 엔진이 조건을 다시 검증한다.
4. 허용된 요청은 Solana Devnet에서 실제 USDC 트랜잭션을 만든다.
5. 수취인·금액·토큰·reference를 온체인에서 검증한다.
6. Base Pay QR, 예산 초과, 미지원 토큰은 서명 전에 거부된다.
7. 동일한 결제 ID를 재실행해도 중복 송금되지 않는다.
8. 새 환경에서 README만 따라 로컬 데모와 테스트를 재현할 수 있다.
9. 비밀키와 실제 자격 증명이 Git에 포함되지 않는다.
10. 3분 영상에서 요청부터 온체인 검증까지 한 흐름으로 확인할 수 있다.

## 4. 사용자 흐름

### 정상 결제

```text
사용자
  → Solana Pay QR 업로드
  → "거래당 1 USDC, 오늘 5 USDC 이내" 정책 선택

에이전트
  → QR 디코딩
  → Solana Pay 형식 확인
  → 수취인·금액·토큰·reference 추출
  → 지갑 잔액 확인
  → 정책 검증
  → 결제 계획 생성
  → 정책 재검증 후 서명
  → Solana 전송
  → 온체인 검증
  → 영수증 반환
```

### 미지원 네트워크

```text
Base Pay QR 업로드
  → Base / 10 USDC 결제 세션으로 분류
  → 지원 네트워크는 Solana뿐임을 확인
  → 트랜잭션을 만들지 않고 거부 사유 반환
```

### 예산 초과

```text
요청 금액: 10 USDC
거래당 한도: 5 USDC
  → 정책 엔진이 서명 전에 차단
  → 지갑 잔액과 일일 사용액은 변경되지 않음
```

## 5. 시스템 아키텍처

```text
┌───────────────────────────────┐
│ Web UI                        │
│ QR 업로드 / 정책 / 실행 상태 │
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ Cloud Run                     │
│ Google ADK Payment Agent      │
│ Gemini                        │
└──────────────┬────────────────┘
               │ Tool calls
      ┌────────┼──────────┬───────────┐
      ▼        ▼          ▼           ▼
 QR Decoder  Intent     Wallet      Payment
             Resolver   Reader      Planner
      └────────┬──────────┴───────────┘
               ▼
┌───────────────────────────────┐
│ Guarded Payment Executor      │
│ Policy / Idempotency / Simulate│
└──────────────┬────────────────┘
               ▼
┌───────────────────────────────┐
│ Solana Devnet / Mainnet       │
└──────────────┬────────────────┘
               ▼
┌───────────────────────────────┐
│ Receipt Verifier              │
│ Firestore / Logging           │
└───────────────────────────────┘
```

### 배포 단위

제출 시점에는 복잡한 마이크로서비스 분리를 하지 않는다.

- `web`: 사용자 데모 UI
- `agent-api`: ADK 에이전트와 결제 코어를 포함하는 Cloud Run 서비스
- `firestore`: 정책·결제 시도·영수증 저장
- `secret-manager`: 배포 환경의 데모 지갑 키와 API 자격 증명

로컬 개발에서는 Firestore 대신 인메모리 또는 SQLite 저장소를 선택할 수 있게 인터페이스를 분리한다.

## 6. 권장 기술 스택

### 에이전트·백엔드

- Python 3.12
- Google Agent Development Kit (`google-adk`)
- Gemini via Vertex AI
- FastAPI 또는 ADK API server
- Pydantic 스키마
- `solders` / `solana-py` 기반 Solana 서명·RPC
- Pillow + ZXing 기반 QR 디코딩
- `httpx` 기반 외부 프로토콜 호출

Python을 우선하는 이유는 공식 ADK/Cloud Run 예제와 평가·세션 도구가 성숙해 있고, 짧은 기간에 에이전트 실행 경로를 명확하게 보여주기 쉽기 때문이다.

### 프론트엔드

- Next.js + TypeScript
- QR 파일 업로드
- 정책 프리셋과 실행 상태 표시
- 도구 실행 타임라인
- 트랜잭션 Explorer 링크

### Google Cloud

- Vertex AI Gemini
- Cloud Run
- Firestore
- Secret Manager
- Cloud Logging

### 테스트

- `pytest`
- 정책 엔진 단위 테스트
- QR fixture 기반 파서 테스트
- Solana RPC 통합 테스트
- 브라우저 핵심 흐름 테스트

구현 중 실제 라이브러리 버전은 lockfile로 고정한다.

## 7. 저장소 구조

```text
agentic-checkout/
├─ apps/
│  ├─ agent_api/
│  │  ├─ agent.py
│  │  ├─ api.py
│  │  ├─ tools/
│  │  │  ├─ decode_qr.py
│  │  │  ├─ resolve_intent.py
│  │  │  ├─ wallet_balance.py
│  │  │  ├─ quote_route.py
│  │  │  ├─ execute_payment.py
│  │  │  └─ verify_payment.py
│  │  └─ services/
│  │     ├─ policy.py
│  │     ├─ idempotency.py
│  │     ├─ solana.py
│  │     └─ receipts.py
│  └─ web/
│     ├─ app/
│     └─ components/
├─ packages/
│  └─ schemas/
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ evals/
├─ scripts/
│  ├─ create_demo_wallet.py
│  ├─ create_sample_qr.py
│  └─ verify_environment.py
├─ docs/
│  ├─ implementation-plan.md
│  └─ architecture.md
├─ .env.example
├─ .gitignore
├─ Dockerfile
├─ Makefile
├─ pyproject.toml
└─ README.md
```

## 8. 공통 PaymentIntent 스키마

모든 입력 형식을 다음 스키마로 정규화한다.

```json
{
  "intent_id": "sha256:...",
  "protocol": "solana_pay",
  "network": "solana:devnet",
  "recipient": "...",
  "amount": "0.10",
  "asset": {
    "symbol": "USDC",
    "mint": "...",
    "decimals": 6
  },
  "reference": "...",
  "label": "Demo Merchant",
  "message": "Order #123",
  "expires_at": null,
  "source_payload_hash": "sha256:...",
  "confidence": "authoritative"
}
```

### 신뢰 수준

- `authoritative`: 표준 결제 요청에 금액·토큰·수취인이 명시됨
- `incomplete`: 주소만 있거나 금액·토큰이 누락됨
- `unsupported`: 인식했지만 지원하지 않는 네트워크·프로토콜
- `invalid`: 형식, 체크섬 또는 필수 필드가 잘못됨

`incomplete`와 `unsupported` 상태에서는 결제 Tool을 호출할 수 없다.

## 9. 에이전트 Tool 계약

### `decode_payment_qr`

입력: 이미지 바이트

출력:

```json
{
  "format": "qr_code",
  "raw_payload": "solana:...",
  "payload_hash": "sha256:..."
}
```

책임:

- QR 문자열 추출만 수행
- URL에 접속하거나 트랜잭션을 만들지 않음
- 이미지 크기와 파일 형식을 제한

### `resolve_payment_intent`

입력: QR 원문

출력: `PaymentIntent` 또는 구조화된 거부 사유

지원 순서:

1. Solana Pay transfer request
2. x402/pay.sh HTTP URL(P1)
3. 명시적 보조 정보가 있는 Solana 주소
4. 알려진 비-Solana 형식 분류

### `get_wallet_balances`

입력: 지갑 공개키

출력: SOL·허용 SPL 토큰 잔액과 최신 slot

개인키는 Tool 입력이나 LLM 컨텍스트에 포함하지 않는다.

### `quote_payment_route`

P0에서는 직접 USDC 결제만 반환한다. P2에서 Jupiter 견적을 추가한다.

출력 예시:

```json
{
  "route": "direct_usdc",
  "input_amount": "0.10",
  "output_amount": "0.10",
  "estimated_network_fee_lamports": 5000,
  "expires_at": "..."
}
```

### `execute_guarded_payment`

Gemini가 직접 서명하지 않는다. 이 함수 내부에서 아래 순서를 강제한다.

1. PaymentIntent 재파싱
2. 네트워크·mint allowlist 재검증
3. 최신 정책 및 일일 사용액 조회
4. intent ID 기반 중복 결제 확인
5. 예산 임시 예약
6. 잔액과 수수료 확인
7. 트랜잭션 생성·시뮬레이션
8. 수취인·금액·mint·reference 검사
9. 서명 및 전송
10. 결과 저장 또는 예약 해제

### `verify_payment`

다음 조건을 모두 확인한다.

- 트랜잭션 성공
- 예상 수취인의 토큰 계정으로 전송
- 정확한 mint
- 정확한 금액
- 예상 reference 또는 주문 식별자
- 이미 사용된 서명이 아님

## 10. 정책 엔진

### 정책 예시

```json
{
  "enabled": true,
  "allowed_networks": ["solana:devnet"],
  "allowed_assets": ["USDC"],
  "allowed_merchants": ["demo-merchant"],
  "max_per_transaction_usd": "1.00",
  "max_daily_usd": "5.00",
  "max_transactions_per_day": 10,
  "max_network_fee_lamports": 100000,
  "max_slippage_bps": 50,
  "expires_at": "2026-08-04T00:00:00+09:00"
}
```

### 불변 조건

- 금액 계산에 부동소수점을 사용하지 않는다.
- mint 주소를 심볼보다 우선한다.
- 일일 예산은 결제 직전 원자적으로 예약한다.
- 결제 실패 시 예약을 해제하되 실패 기록은 남긴다.
- intent ID, 사용자, 세션을 묶어 idempotency key를 만든다.
- LLM 출력만으로 판매자 allowlist를 통과시키지 않는다.
- 원본 결제 요청과 해시는 authorization 생성 시 서버에 고정하고, 실행 Tool은
  LLM이 전달한 결제 문자열을 받지 않는다.
- QR의 표시용 `label`은 판매자 신원 증명으로 사용하지 않는다.

## 11. 지갑 및 키 관리

### 로컬·재현 환경

- 스크립트로 새로운 Devnet 전용 지갑 생성
- 키 파일은 Git ignore
- 환경변수로 키 파일 경로만 전달
- 테스트 기본값은 mock signer
- 실제 통합 테스트는 명시적 플래그가 있을 때만 실행

### Cloud Run 데모

- 소액 데모 지갑만 사용
- Secret Manager에서 런타임에 키 로드
- Gemini 프롬프트·로그·Firestore에 비밀키를 기록하지 않음
- 지갑 잔액 자체를 손실 상한으로 사용

### 상용화 방향

P0의 서버 보관 데모 지갑은 해커톤 구현이다. 실제 제품에서는 Solana Allowance, 스마트 계정 또는 제한된 delegated signer로 교체한다.

## 12. 데이터 모델

### `policies`

- `user_id`
- 허용 네트워크·토큰·판매자
- 거래·일일 한도
- 만료 시각
- 버전

### `payment_attempts`

- `intent_id`
- `idempotency_key`
- `status`: decoded / rejected / reserved / submitted / confirmed / failed
- 정책 스냅샷
- 거부 코드
- 트랜잭션 서명
- 생성·수정 시각

### `receipts`

- 네트워크
- 서명
- 수취인
- mint
- 금액
- reference
- Explorer URL
- 검증 시각

## 13. API 초안

```text
POST /api/qr/decode
POST /api/intents/resolve
POST /api/agent/run
GET  /api/payments/{intent_id}
GET  /api/wallet/balances
GET  /healthz
```

웹 UI는 가능하면 `/api/agent/run`만 사용하고, 나머지 엔드포인트는 테스트·디버깅용으로 둔다.

## 14. 테스트 계획

| ID | 시나리오 | 기대 결과 | 실제 온체인 |
|---|---|---|---|
| T01 | 유효한 Solana Pay USDC QR | intent 생성 | 아니오 |
| T02 | 제공된 Base Pay 10 USDC QR | `unsupported_network` | 아니오 |
| T03 | 일반 URL QR | `unsupported_protocol` | 아니오 |
| T04 | 손상된 QR | `decode_failed` | 아니오 |
| T05 | 거래당 한도 초과 | 서명 전 거부 | 아니오 |
| T06 | 일일 한도 초과 | 서명 전 거부 | 아니오 |
| T07 | 미허용 mint | 서명 전 거부 | 아니오 |
| T08 | 잔액 부족 | 서명 전 거부 | 아니오 |
| T09 | 유효한 Devnet USDC 결제 | confirmed + receipt | 예 |
| T10 | 동일 intent 재실행 | 기존 결과 반환, 재송금 없음 | 아니오 |
| T11 | 잘못된 수취인으로 변조 | 실행 직전 거부 | 아니오 |
| T12 | reference 불일치 | 검증 실패 | 예/fixture |
| T13 | x402 유료 엔드포인트(P1) | 결제 후 200 응답 | 예 |
| T14 | USDT→USDC→결제(P2) | swap + payment 영수증 | 예 |

## 15. ADK 평가 시나리오

최종 답변뿐 아니라 도구 호출 궤적을 평가한다.

### 성공 trajectory

```text
decode_payment_qr
→ resolve_payment_intent
→ get_wallet_balances
→ quote_payment_route
→ execute_guarded_payment
→ verify_payment
```

### 거부 trajectory

```text
decode_payment_qr
→ resolve_payment_intent
→ unsupported_network
→ 종료
```

잘못된 trajectory 예시:

- intent를 해석하기 전에 결제 도구 호출
- 예산 초과인데 실행 도구 호출
- Base Pay 요청에 Solana 송금 시도
- 결제 검증 없이 성공 응답

## 16. 관측성과 감사 로그

반드시 기록할 이벤트:

- QR decode 성공·실패
- protocol/network 분류
- 정책 결과와 거부 코드
- 도구 호출 순서
- 예산 예약·해제
- 트랜잭션 제출·확정
- 최종 검증 결과

로그에 남기지 않을 항목:

- 개인키와 seed phrase
- 서명 전 원본 비밀 데이터
- 전체 사용자 입력 이미지의 영구 저장본
- 필요 이상의 지갑 정보

## 17. 구현 일정

### 8월 1일: 로컬 수직 슬라이스

1. 프로젝트 scaffold 및 의존성 고정
2. `PaymentIntent`와 정책 스키마 구현
3. QR 디코더 및 Solana Pay/Base Pay 분류
4. 정책 엔진과 idempotency 단위 테스트
5. ADK 에이전트에 읽기 전용 Tool 연결
6. mock 결제까지 전체 흐름 완성

완료 기준:

- Solana Pay QR는 정상 intent 생성
- Base Pay QR는 명확하게 거부
- 예산 초과 테스트 통과

### 8월 2일: 실제 온체인 및 배포

1. Devnet 지갑·RPC 설정
2. USDC 전송 생성·시뮬레이션·서명
3. reference 기반 검증
4. 웹 UI 연결
5. Cloud Run 배포
6. 실제 Devnet 성공·실패 시나리오 녹화

완료 기준:

- Cloud Run에서 Agent 호출 가능
- Explorer에서 Devnet 결제 확인 가능
- 중복 결제 방지 확인

### 8월 3일: 제출물 완성

1. x402/pay.sh P1 기능 추가 여부 결정
2. README를 새 환경 기준으로 재실행
3. 테스트·eval 결과 정리
4. 아키텍처 다이어그램 확정
5. 3분 데모 영상 촬영
6. 소개서와 GitHub 링크 검수
7. 제출 마감 전 라이브 엔드포인트 확인

### 기능 동결 규칙

- P0가 모두 통과하기 전에는 Jupiter, 브리지, 멀티에이전트를 시작하지 않는다.
- 8월 3일 오전까지 Cloud Run이 불안정하면 로컬 데모를 기준으로 영상을 먼저 확보한다.
- 메인넷 기능이 실패하면 Devnet 실제 결제를 제출 기준으로 유지한다.

## 18. 3분 데모 구성

### 0:00–0:25 문제

- Base Pay QR를 제시
- 사용자가 네트워크·지갑·자산을 알아야 하는 불편 설명

### 0:25–0:50 정책 설정

```text
거래당 1 USDC
일일 5 USDC
Solana / USDC만 허용
```

### 0:50–1:15 안전한 거부

- Base Pay QR 업로드
- Base / 10 USDC로 정확히 분류
- 지원하지 않는 네트워크라 결제하지 않음

### 1:15–2:20 실제 결제

- Solana Pay QR 업로드
- Gemini/ADK 도구 실행 타임라인
- 정책 통과
- 실제 Devnet USDC 결제
- 온체인 검증

### 2:20–2:45 안전성

- 한도 초과 요청
- 서명 전 정책 거부

### 2:45–3:00 확장성

- x402/pay.sh 어댑터
- Jupiter 자산 변환
- Solana Allowance
- Base/WalletConnect 등 프로토콜 어댑터 구조

## 19. 제출 체크리스트

### GitHub

- [ ] 공개 저장소 접근 가능
- [ ] `.env.example`
- [ ] lockfile
- [ ] 원클릭 또는 명확한 실행 명령
- [ ] 테스트 명령
- [ ] Devnet 지갑 준비 방법
- [ ] 샘플 QR fixture
- [ ] 실제 트랜잭션 예시
- [ ] Cloud Run 배포 방법
- [ ] 알려진 제한사항
- [ ] 라이선스

### 소개서

- [ ] 타깃 사용자·기관
- [ ] 문제와 실제 Base Pay 사례
- [ ] 솔루션과 차별점
- [ ] 수익 모델
- [ ] 도입 시나리오
- [ ] 아키텍처
- [ ] 정책 기반 안전성
- [ ] 현재 범위와 향후 멀티체인 확장 구분

### 영상

- [ ] 3분 이내
- [ ] 실제 온체인 결제 전 과정
- [ ] Explorer 링크 또는 서명 확인 가능
- [ ] 정책 거부 사례
- [ ] Gemini가 실제 Tool을 호출하는 화면

## 20. 주요 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| Devnet USDC 확보 또는 RPC 불안정 | 라이브 결제 실패 | 사전 지갑 준비, RPC fallback, 성공 영상 선확보 |
| LLM이 결제 순서를 건너뜀 | 안전성 문제 | 실행 함수 내부 정책 강제 |
| QR에 금액·토큰 누락 | 잘못된 결제 | `incomplete`로 종료, 추측 금지 |
| 중복 요청 | 이중 송금 | idempotency key + 상태 저장 |
| 키 노출 | 자금 손실 | 전용 소액 지갑 + Secret Manager + 로그 필터링 |
| Jupiter Devnet 유동성 부족 | 스왑 데모 실패 | 스왑은 Mainnet 선택 기능으로 격리 |
| pay.sh 기본 사용자 승인 흐름 | 자율성 점수 약화 | P0 전용 에이전트 지갑, 향후 Allowance 명시 |
| Base 사례가 Solana와 혼동됨 | 심사 메시지 약화 | Base는 문제·거부 사례, 성공 정산은 Solana로 분리 |

## 21. 구현 의사결정 요약

1. 제품 본체는 Gemini 기반 Google ADK 단일 에이전트다.
2. 웹은 에이전트를 시연하기 위한 클라이언트다.
3. P0 성공 경로는 Solana Pay QR → Devnet USDC 직접 결제다.
4. 제공된 Base Pay QR는 형식 인식과 정책 기반 거부 fixture로 사용한다.
5. Gemini는 도구 순서를 결정하지만 결제 권한을 직접 소유하지 않는다.
6. 실제 서명은 정책 강제 executor만 수행한다.
7. x402/pay.sh는 두 번째 입력 어댑터로 추가한다.
8. Jupiter와 크로스체인은 P0 이후 기능이다.

## 22. 공식 참고자료

- Google ADK / Cloud Run: https://docs.cloud.google.com/run/docs/ai/build-and-deploy-ai-agents/deploy-adk-agent
- Solana Pay: https://solana.com/docs/tools/solana-pay
- Solana Pay transfer request: https://solana.com/docs/tools/solana-pay/quickstart/transfer-requests
- x402 buyer quickstart: https://docs.cdp.coinbase.com/x402/quickstart-for-buyers
- pay.sh docs: https://pay.sh/docs
- Solana Allowances: https://solana.com/news/subscriptions-and-allowances
