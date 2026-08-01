# Solana Devnet 지갑 및 테스트 자산 준비

## 안전 원칙

- P0는 Solana Devnet만 허용한다.
- RPC 작업 전에 genesis hash가 Devnet인지 검증한다.
- Circle 공식 Devnet USDC mint만 허용한다.
- 키 파일은 `.secrets/` 아래에 저장하며 Git에 포함하지 않는다.
- 명령 출력에는 공개키만 표시하며 키 파일 내용은 출력하지 않는다.
- 이 지갑에는 Devnet 테스트 자산만 보관한다.

## 지갑 생성 및 RPC 확인

프로젝트 루트에서 다음 명령을 실행한다.

```powershell
.\.venv\Scripts\python.exe scripts\setup_devnet_wallet.py
```

처음 실행하면 `.secrets/devnet-agent-keypair.json`을 생성한다. 이후에는 기존
파일을 다시 불러오며 덮어쓰지 않는다.

정상 출력에서는 다음 항목을 확인한다.

- genesis hash: `EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG`
- USDC mint: `4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU`
- USDC decimals: `6`

## Devnet SOL 준비

프로그램 방식으로 최소 잔액까지 요청할 수 있다.

```powershell
.\.venv\Scripts\python.exe scripts\setup_devnet_wallet.py --minimum-sol 0.1
```

공개 RPC는 에어드롭을 제한하거나 HTTP 429를 반환할 수 있다. 그 경우 반복
요청하지 말고 [Solana Devnet Faucet](https://faucet.solana.com/)에서 스크립트가
출력한 공개 주소로 Devnet SOL을 받은 뒤, 인자 없이 스크립트를 다시 실행한다.

## Devnet USDC 준비

SOL 에어드롭은 USDC를 지급하지 않는다. [Circle Faucet](https://faucet.circle.com/)에서
네트워크를 Solana Devnet으로 선택하고 동일한 공개 주소에 테스트 USDC를 지급한다.
Circle Devnet USDC는 실제 달러 가치가 없다.

## Git 포함 여부 확인

다음 명령은 키 파일 자체를 읽지 않고 ignore 규칙만 확인한다.

```powershell
git check-ignore -v .secrets/devnet-agent-keypair.json
```

`.gitignore`의 `.secrets/` 규칙이 표시되어야 한다.

## 제출 없는 실제 RPC simulation

다음 명령은 최신 Devnet blockhash로 USDC 거래를 만들고 로컬 키로 서명한 뒤
RPC simulation까지만 수행한다. `sendTransaction`은 호출하지 않는다.

```powershell
.\.venv\Scripts\python.exe scripts\prepare_devnet_transfer.py `
  --recipient <SOLANA_RECIPIENT> `
  --reference <SOLANA_PAY_REFERENCE> `
  --amount 0.10
```

출력의 마지막 줄은 항상 `Submitted: false`다. SOL 또는 USDC가 부족하면
`AccountNotFound`나 잔액 부족 오류가 정상적으로 표시되며 온체인 거래는 생기지 않는다.

## ADK 실행 모드와 사용자 authorization

기본값은 다음과 같이 `mock`이다. 이 상태에서 ADK 실행 도구는 실제 RPC 제출이나
키 파일 서명을 수행하지 않는다.

```dotenv
PAYMENT_EXECUTION_MODE=mock
```

사용자는 먼저 `POST /api/authorizations`에 세션 ID와 `SpendingPolicy`를 등록해야 한다.
API가 반환한 `authorization_id`만 Gemini의 `execute_authorized_checkout` 도구에 전달한다.
이 도구는 모델 입력에서 정책 한도, 판매자 ID, 지갑 경로, RPC 주소를 받지 않는다.

실제 Devnet 데모 직전에만 아래 값을 `.env`에 설정하고 프로세스를 재시작한다.

```dotenv
PAYMENT_EXECUTION_MODE=devnet
DEMO_MERCHANT_ID=demo-merchant
DEMO_MERCHANT_RECIPIENT=<검증된 Solana Devnet 수취 주소>
```

실행기는 QR의 수취 주소가 `DEMO_MERCHANT_RECIPIENT`와 정확히 일치할 때만 해당
판매자를 검증된 대상으로 취급한다. 정책 거부 또는 simulation 실패는 제출 전에
종료되며, 제출 후 확인이 불완전한 거래는 자동 재전송하지 않는다.

로컬 authorization 저장소는 프로세스 재시작 시 초기화된다. Cloud Run 배포 전에는
이 API에 사용자 인증을 추가하고 저장소를 Firestore 트랜잭션으로 교체해야 한다.
