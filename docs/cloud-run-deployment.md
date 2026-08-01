# Cloud Run 배포 가이드

이 문서는 P0의 `agent-api`를 Cloud Run에 배포하는 절차를 설명한다. 먼저 실제
지갑에 접근하지 않는 `mock` 모드로 배포하고, API와 Gemini 호출이 확인된 뒤에만
Devnet 키 파일을 Secret Manager로 연결한다.

## 1. 사전 준비

- Google Cloud 프로젝트와 Billing 연결
- Google Cloud CLI 설치 및 로그인
- Cloud Run, Cloud Build, Artifact Registry, Vertex AI, Secret Manager API 활성화
- 배포 계정에 Cloud Run Source Developer 및 Service Account User 권한
- 런타임 서비스 계정에 Vertex AI User 권한

공식 ADK Cloud Run 가이드는 소스 배포 전에 Cloud Run Admin API, Vertex AI API,
Cloud Build API를 활성화하도록 안내한다.

```powershell
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud services enable `
  run.googleapis.com `
  cloudbuild.googleapis.com `
  artifactregistry.googleapis.com `
  aiplatform.googleapis.com `
  secretmanager.googleapis.com
```

## 2. Mock 모드 소스 배포

프로젝트 루트의 `Dockerfile`은 FastAPI와 ADK Runner를 8080 포트로 실행한다.
Cloud Run은 `--source .` 배포에서 이 Dockerfile을 사용해 이미지를 빌드한다.

```powershell
gcloud run deploy agentic-checkout-api `
  --source . `
  --region asia-northeast3 `
  --allow-unauthenticated `
  --max-instances 1 `
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=<PROJECT_ID>,GOOGLE_CLOUD_LOCATION=asia-northeast3,GEMINI_MODEL=gemini-2.5-flash,PAYMENT_EXECUTION_MODE=mock,CORS_ALLOWED_ORIGINS=<WEB_ORIGIN>"
```

배포 후 출력된 URL에서 다음을 확인한다.

```powershell
Invoke-RestMethod https://<SERVICE_URL>/healthz
```

응답은 `{"status":"ok"}`여야 한다. 로컬 authorization 저장소를 사용하므로 P0
배포는 `max-instances=1`로 제한한다. 인스턴스 재시작 시 authorization과 결제 원장이
초기화되는 것은 현재 알려진 제한사항이다.

## 3. Devnet 키 파일을 Secret Manager에 저장

키 파일은 이미지, Git, 일반 환경 변수에 포함하지 않는다. 로컬에서 생성한 Devnet
전용 키 파일을 Secret Manager에 별도 secret으로 저장한다.

```powershell
gcloud secrets create agentic-checkout-devnet-keypair `
  --replication-policy automatic `
  --data-file .secrets/devnet-agent-keypair.json
```

Cloud Run 런타임 서비스 계정에는 해당 secret의 Secret Manager Secret Accessor
권한만 부여한다. 실제 운영 자산이나 메인넷 키는 이 P0 서비스에 사용하지 않는다.

## 4. Devnet 실행 모드 배포

지갑에 Devnet SOL과 Circle Devnet USDC가 준비된 뒤 아래와 같이 secret을 파일로
마운트한다. Cloud Run의 secret 경로는 선행 `/`가 있는 전체 파일 경로여야 한다.

```powershell
gcloud run deploy agentic-checkout-api `
  --source . `
  --region asia-northeast3 `
  --allow-unauthenticated `
  --max-instances 1 `
  --update-secrets "/var/run/agent-secrets/devnet-agent-keypair.json=agentic-checkout-devnet-keypair:latest" `
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=<PROJECT_ID>,GOOGLE_CLOUD_LOCATION=asia-northeast3,GEMINI_MODEL=gemini-2.5-flash,PAYMENT_EXECUTION_MODE=devnet,SOLANA_NETWORK=devnet,SOLANA_RPC_URL=https://api.devnet.solana.com,SOLANA_KEYPAIR_PATH=/var/run/agent-secrets/devnet-agent-keypair.json,DEMO_MERCHANT_ID=demo-merchant,DEMO_MERCHANT_RECIPIENT=<VERIFIED_RECIPIENT>,CORS_ALLOWED_ORIGINS=<WEB_ORIGIN>"
```

Devnet 배포 후에는 순서대로 확인한다.

1. `/healthz`
2. Gemini가 `inspect_payment_request`를 호출하는 mock 또는 소액 요청
3. `get_agent_wallet_balances` 결과
4. 거래당 한도보다 작은 Devnet USDC 결제
5. 반환된 Explorer URL의 수취인·mint·금액·reference
6. 동일 intent 재호출 시 중복 제출이 발생하지 않는지

## 5. 현재 제한사항

- authorization·예산 원장이 메모리에 있어 다중 인스턴스를 지원하지 않는다.
- 공개 데모 API에는 최종 사용자 인증이 없다.
- Cloud Run revision 재시작 시 로컬 상태가 사라진다.
- P0는 Solana Devnet 공식 Circle USDC와 등록된 단일 판매자만 지원한다.
- 메인넷, 브리지, Jupiter, pay.sh/x402는 현재 배포 범위가 아니다.

배포 이후에는 Firestore 트랜잭션 기반 원장과 사용자 인증을 추가해야 다중 인스턴스와
지속적인 authorization을 안전하게 지원할 수 있다.
