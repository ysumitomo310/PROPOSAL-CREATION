# AWS デプロイ 実装計画

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** AWSアカウントのみの状態から、会社メンバーが利用できる本番環境を構築する

**Architecture:** EC2 t3.xlarge + Docker Compose + Nginx。会社グローバルIPからのみアクセス可（セキュリティグループ制限）。平日9〜19時のみ自動起動。

**Tech Stack:** Amazon Linux 2023, Docker Compose v2, Nginx, EventBridge Scheduler

---

## 全体フロー

```
Phase 0: AWS初期設定         (AWSコンソール / ブラウザ操作)
Phase 1: ネットワーク設定     (AWSコンソール)
Phase 2: EC2起動             (AWSコンソール)
Phase 3: EC2初期セットアップ  (SSH)
Phase 4: コード変更          (ローカル / git push)
Phase 5: アプリデプロイ       (EC2上でのSSH操作)
Phase 6: 自動起動・停止設定   (AWSコンソール)
Phase 7: 動作確認
```

---

## Phase 0: AWS初期設定

> **目的:** rootアカウントを使わず、管理用IAMユーザーを作成する。rootは漏れたら全て失う。

### Task 0-1: MFAとIAMユーザー設定

**Step 1: AWSコンソールにrootでログイン**

- ブラウザで https://console.aws.amazon.com/ を開く
- rootアカウント（メールアドレス）でログイン

**Step 2: rootのMFAを有効化**

- 右上アカウント名 → 「セキュリティ認証情報」
- 「多要素認証 (MFA)」→「MFAを割り当てる」
- 認証アプリ（Google Authenticator等）でQRコードをスキャン
- 確認コードを2回入力して完了

**Step 3: 管理用IAMユーザーを作成**

- サービス検索で「IAM」→「ユーザー」→「ユーザーを作成」
- ユーザー名: `admin-yourname`（例: `admin-sumitomo`）
- 「IAM ユーザーを作成します」にチェック
- パスワードを設定
- 「次へ」→「直接ポリシーをアタッチ」→「AdministratorAccess」を選択
- 「ユーザーの作成」

**Step 4: IAMユーザーのMFAも設定**

- 作成したユーザーをクリック → 「セキュリティ認証情報」タブ
- MFAデバイスを割り当て（rootと同様の手順）

**Step 5: 以降はIAMユーザーでログイン**

- rootからサインアウト
- IAMユーザーでログイン
- URLは `https://<アカウントID>.signin.aws.amazon.com/console`

---

### Task 0-2: 予算アラート設定

> **目的:** 予期せぬ高額請求を防ぐ（設定ミスで$1000超えの事故が起きやすい）

**Step 1: リージョンを「米国東部（バージニア北部）」に切り替え**

- Billing は us-east-1 でのみ設定可能
- 右上リージョン名をクリック → 「米国東部 (バージニア北部)」

**Step 2: Budgets を開く**

- サービス検索「Budgets」→「予算を作成」

**Step 3: 予算を作成**

- テンプレート: 「月次コスト予算」
- 予算名: `monthly-cost-alert`
- 予算額: `$100`（月$55想定の2倍で安全マージン）
- メールアドレス: 通知を受け取るメールを入力
- 「予算を作成」

**Step 4: 東京リージョンに戻す**

- 右上リージョン → 「アジアパシフィック (東京) ap-northeast-1」

---

## Phase 1: ネットワーク設定

### Task 1-1: 会社のグローバルIPを確認

**Step 1: 会社のネットワークからグローバルIPを調べる**

社内ネットワーク（会社のWiFiまたは有線）に接続した状態で:

```
https://whatismyip.com/
```

表示された「Your IPv4 Address」をメモ。例: `203.0.113.10`

> **注意:** 会社のIPが固定IPかどうかを情シスに確認すること。動的IPなら毎月変わる可能性があり、その都度セキュリティグループを更新する必要がある。

**Step 2: 自分の自宅IP（管理作業用）もメモ**

自宅から作業する場合は自宅のIPも必要。SSH接続用に追加する。

---

### Task 1-1b: デフォルトVPCの確認・作成

> **目的:** セキュリティグループを作成するにはVPCが必要。AWSは通常デフォルトVPCを自動作成しているが、削除されている場合がある。

**Step 1: VPCコンソールを開く**

サービス検索「VPC」→ 左メニュー「お使いのVPC」

**Step 2: デフォルトVPCを確認**

一覧に「デフォルト: はい」の行があれば **このタスクはスキップ**。Task 1-2へ進む。

**Step 3: デフォルトVPCがない場合 → 作成**

- 右上「アクション」→「**デフォルトVPCを作成**」
- 確認ダイアログで「デフォルトVPCを作成」
- 完了まで30秒ほど待つ

作成されると以下が自動で揃う:
```
デフォルトVPC (172.31.0.0/16)
├── パブリックサブネット × 3（ap-northeast-1a, 1c, 1d）
├── インターネットゲートウェイ
└── ルートテーブル（全サブネットからインターネットへのルート）
```

---

### Task 1-2: セキュリティグループの作成

> **目的:** 「どのIPからのどのポートへのアクセスを許可するか」を定義するファイアウォール。

**Step 1: EC2コンソールを開く**

- サービス検索「EC2」→ 左メニュー「セキュリティグループ」（「ネットワーク＆セキュリティ」の下）

**Step 2: セキュリティグループを作成**

「セキュリティグループを作成」をクリック

```
セキュリティグループ名: proposal-creation-sg
説明: ProposalCreation application security group
VPC: デフォルトVPC（変更不要）
```

**Step 3: インバウンドルールを追加**

「インバウンドルールを追加」を4回クリックして以下を設定:

| タイプ | プロトコル | ポート | ソース | 説明 |
|-------|----------|-------|-------|------|
| SSH | TCP | 22 | カスタム: `<管理者自宅IP>/32` | 管理者SSH（自宅） |
| SSH | TCP | 22 | カスタム: `<会社グローバルIP>/32` | 管理者SSH（会社） |
| HTTP | TCP | 80 | カスタム: `<会社グローバルIP>/32` | アプリHTTP |
| カスタムTCP | TCP | 7474 | カスタム: `<管理者IP>/32` | Neo4j Browser（任意） |

> **ポイント:** `/32` はその1つのIPだけを指す。`/24` にするとサブネット全体になる（危険）。

**Step 4: アウトバウンドルール**

デフォルト（全て許可）のまま変更不要。

**Step 5: 「セキュリティグループを作成」**

作成されたセキュリティグループIDをメモ（例: `sg-0123456789abcdef0`）

---

## Phase 2: EC2インスタンスの起動

### Task 2-1: キーペアの作成

> **目的:** EC2にSSH接続するための秘密鍵。一度しかダウンロードできないので注意。

**Step 1: キーペアを作成**

- EC2コンソール → 左メニュー「キーペア」→「キーペアを作成」

```
名前: proposal-creation-key
キーペアのタイプ: RSA
プライベートキーファイル形式: .pem（Mac/Linux） or .ppk（Windowsでputty使用時）
```

Windows + WinSCP/Puttyの場合は `.ppk`、WSL/PowerShell/Terminalの場合は `.pem`

**Step 2: ダウンロードされた .pem ファイルを安全な場所に保存**

```
推奨: C:\Users\<ユーザー名>\.ssh\proposal-creation-key.pem
```

**Step 3: 権限を設定（Mac/Linuxの場合）**

```bash
chmod 400 ~/.ssh/proposal-creation-key.pem
```

Windowsの場合はファイルを右クリック→プロパティ→セキュリティで自分のみ読み取り権限に変更

---

### Task 2-2: EC2インスタンスの起動

**Step 1: 「インスタンスを起動」をクリック**

EC2コンソールのダッシュボード → オレンジ色の「インスタンスを起動」ボタン

**Step 2: 各項目を設定**

```
名前: proposal-creation-server

Amazon マシンイメージ (AMI):
  「Amazon Linux 2023 AMI」を選択
  （「無料利用枠の対象」バッジはあっても無視。AMIの選択が重要）

インスタンスタイプ:
  t3.xlarge を選択
  （検索窓に「t3.xlarge」と入力すると絞り込める）

キーペア:
  「proposal-creation-key」を選択

ネットワーク設定:
  「既存のセキュリティグループを選択する」
  「proposal-creation-sg」にチェック

ストレージ:
  「1x 8 GiB」→ 「50」GiBに変更
  ボリュームタイプ: gp3（デフォルト）
  （Neo4j + PostgreSQL + Dockerイメージ用に余裕を持たせる）
```

**Step 3: 「インスタンスを起動」**

インスタンスIDが表示される（例: `i-0123456789abcdef0`）

**Step 4: インスタンスが「実行中」になるまで待機**

EC2コンソール → インスタンス一覧で「インスタンスの状態」が「実行中」になるまで1〜2分待つ

---

### Task 2-3: Elastic IPの設定

> **目的:** EC2を再起動するたびにIPが変わると困る。固定IPを割り当てる。
>
> **タイミング:** EventBridge自動起動・停止の設定（Phase 6）と同時でもよい。セットアップ・動作確認フェーズは動的IPでも問題ない（1人で作業する場合）。
> Elastic IP設定後は `.env` の `ALLOWED_ORIGINS` と `EC2_ELASTIC_IP` を更新し、`docker compose up -d --build frontend` で再ビルドが必要。

**Step 1: Elastic IPを割り当て**

- EC2コンソール → 左メニュー「Elastic IP」→「Elastic IPアドレスを割り当て」
- デフォルト設定のまま「割り当て」
- 割り当てられたIPアドレスをメモ（例: `13.114.xxx.xxx`）← これが今後のアクセス先

**Step 2: EC2インスタンスに関連付け**

- 割り当てたElastic IPを選択
- 「Elastic IPアドレスの関連付け」
- インスタンス: 「proposal-creation-server」を選択
- 「関連付け」

> **料金メモ:** EC2が**起動中**はElastic IP無料。EC2**停止中**は$0.005/時間かかる。今回は停止時間が月510時間なので約$2.55/月（約400円）の追加コスト。許容範囲として受け入れる。

---

## Phase 3: EC2初期セットアップ

### Task 3-1: SSH接続確認

**Step 1: SSH接続（Windows PowerShellまたはTerminal）**

```powershell
ssh -i "C:\Users\<ユーザー名>\.ssh\proposal-creation-key.pem" ec2-user@13.114.xxx.xxx
```

`13.114.xxx.xxx` は割り当てたElastic IPに置き換える。

初回接続時に「Are you sure you want to continue connecting (yes/no)?」と聞かれたら `yes` を入力。

**Step 2: 接続確認**

以下のプロンプトが表示されれば成功:
```
   ,     #_
   ~\_  ####_        Amazon Linux 2023
  ~~  \_#####\
  ~~     \###|       https://aws.amazon.com/linux/amazon-linux-2023
  ~~       \#/ ___
   ~~       V~' '->
    ~~~         /
      ~~._.   _/
         _/ _/
       _/m/'
[ec2-user@ip-xxx ~]$
```

---

### Task 3-2: Dockerのインストール

**Step 1: システムアップデート**

```bash
sudo dnf update -y
```

完了まで1〜2分かかる。

**Step 2: Dockerインストール**

```bash
sudo dnf install -y docker git
```

**Step 3: Docker起動・自動起動設定**

```bash
sudo systemctl start docker
sudo systemctl enable docker
```

確認:
```bash
sudo systemctl status docker
```
`Active: active (running)` と表示されればOK。`q` で終了。

**Step 4: ec2-userをdockerグループに追加**

```bash
sudo usermod -aG docker ec2-user
```

**Step 5: Docker Compose v2のインストール**

```bash
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
```

**Step 6: 再ログイン（dockerグループ反映）**

```bash
exit
```

再度SSH接続する:
```powershell
ssh -i "C:\Users\<ユーザー名>\.ssh\proposal-creation-key.pem" ec2-user@13.114.xxx.xxx
```

**Step 7: Docker動作確認**

```bash
docker --version
docker compose version
```

期待出力例:
```
Docker version 25.0.x, build xxxxxxx
Docker Compose version v2.x.x
```

---

### Task 3-3: Nginxのインストール

```bash
sudo dnf install -y nginx
sudo systemctl enable nginx
```

まだ起動しない（設定ファイルを作ってから起動する）。

---

## Phase 4: コード変更（ローカルPCでの作業）

> **目的:** 開発用設定を本番用に修正する。ここからはローカルPCでの作業。

### Task 4-1: Frontend Dockerfileを本番対応に修正

**対象ファイル:** `frontend/Dockerfile`

現在の問題: `pnpm dev`（開発サーバー）を使っている。本番は `pnpm run build && pnpm start` が必要。
また、`NEXT_PUBLIC_API_URL` はビルド時に埋め込まれるため、ARGで受け取れるようにする。

**Step 1: frontend/Dockerfileを以下に書き換える**

```dockerfile
FROM node:22-alpine AS base

WORKDIR /app

RUN npm install -g pnpm

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY . .

# ビルド時にAPIのURLを受け取る
ARG NEXT_PUBLIC_API_URL=http://localhost/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN pnpm run build

EXPOSE 3000

CMD ["pnpm", "start"]
```

**Step 2: ローカルで動作確認（任意）**

変更後も `docker compose --profile full up` でローカル動作することを確認。

---

### Task 4-2: Backend CORSを環境変数対応に修正

**対象ファイル:** `backend/app/core/config.py` と `backend/app/main.py`

現在の問題: CORSのallowed_originsがハードコード（localhostのみ）。
EC2のIPを許可できるよう、環境変数から読み込む。

**Step 1: config.pyにALLOWED_ORIGINSを追加**

[backend/app/core/config.py](backend/app/core/config.py) の `Settings` クラスに以下を追加（`MAPPING_ERROR_THRESHOLD` の下）:

```python
# === CORS ===
ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
```

**Step 2: main.pyのCORSミドルウェアを修正**

[backend/app/main.py](backend/app/main.py) の49行目付近を修正:

変更前:
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
```

変更後:
```python
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.ALLOWED_ORIGINS.split(",")],
```

> **注意:** この変更後、`settings = get_settings()` を `lifespan` の外で呼ぶことになる。
> FastAPIの起動時に一度だけ呼ばれるため問題ない。

**Step 3: ローカルで起動確認**

```bash
docker compose --profile full up --build
```

`http://localhost:3001` でアクセスできることを確認。

---

### Task 4-3: docker-compose.prod.yml を作成

**対象ファイル:** `docker-compose.prod.yml`（新規作成、プロジェクトルート）

```yaml
# 本番環境用オーバーライド
# 使い方: docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile full up -d --build
services:
  backend:
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
    volumes: []
    restart: always

  frontend:
    build:
      args:
        NEXT_PUBLIC_API_URL: http://${EC2_ELASTIC_IP}/api
    volumes: []
    restart: always

  postgres:
    restart: always
    ports:
      - "127.0.0.1:5432:5432"  # localhostのみ（外部非公開）

  neo4j:
    restart: always
    ports:
      - "127.0.0.1:7687:7687"  # localhostのみ（外部非公開）
      - "7474:7474"             # Neo4j Browser（セキュリティグループで制限）
```

> **ポイント:** PostgreSQLとNeo4jのBoltポートを `127.0.0.1:` にバインドすることで、EC2外部から直接アクセス不可にする（セキュリティグループとの二重防御）。

---

### Task 4-4: Nginx設定ファイルを作成

**対象ファイル:** `nginx/nginx.conf`（新規作成）

```nginx
server {
    listen 80;

    # バックエンドAPI（/api/配下をFastAPIに転送）
    location /api/ {
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;  # LLM処理は時間がかかるため延長
        proxy_send_timeout 300s;
        client_max_body_size 50M; # RFPファイルアップロード対応
    }

    # フロントエンド（それ以外はNext.jsに転送）
    location / {
        proxy_pass http://localhost:3001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
    }
}
```

---

### Task 4-5: 変更をgit pushする

> **注意:** `docker-compose.prod.yml` にグローバルIPを直接書かない。`${EC2_ELASTIC_IP}` で環境変数参照にすること（`.env` はgitignore済みなのでIPがgitに入らない）。

```bash
git add frontend/Dockerfile backend/app/core/config.py backend/app/main.py docker-compose.prod.yml nginx/nginx.conf
git commit -m "feat: add production deployment configuration"
git push origin main
```

---

## Phase 5: アプリデプロイ（EC2での作業）

> EC2にSSH接続した状態で作業する。

### Task 5-1: リポジトリをクローン

```bash
cd ~
git clone https://github.com/<your-org>/<your-repo>.git ProposalCreation
cd ProposalCreation
```

`<your-org>/<your-repo>` は実際のGitHubリポジトリ名に置き換える。

確認:
```bash
ls
```
`docker-compose.yml`, `docker-compose.prod.yml`, `backend/`, `frontend/` 等が表示されれば OK。

---

### Task 5-2: .envファイルの作成

```bash
cat > .env << 'EOF'
# ---- LLM API Keys ----
OPENAI_API_KEY=sk-proj-ここに実際のキーを入力
ANTHROPIC_API_KEY=sk-ant-api03-ここに実際のキーを入力

# ---- PostgreSQL ----
POSTGRES_HOST=proposal-creation-postgres
POSTGRES_PORT=5432
POSTGRES_DB=proposal_creation
POSTGRES_USER=proposal_user
POSTGRES_PASSWORD=ここに強力なパスワードを設定（例：Xk9#mP2$vL8nQ4）

# ---- Neo4j ----
NEO4J_URI=bolt://proposal-creation-neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=ここに強力なパスワードを設定（例：Rj5@wT1&hN6yC3）

# ---- LangSmith ----
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls-ここに実際のキーを入力
LANGCHAIN_PROJECT=proposal-creation-prod

# ---- LLM Models ----
LLM_LIGHT_MODEL=gpt-4o-mini
LLM_HEAVY_MODEL=claude-sonnet-4-5-20250929
MAPPING_MAX_CONCURRENCY=5
MAPPING_ERROR_THRESHOLD=0.2

# ---- CORS ----
ALLOWED_ORIGINS=http://13.114.xxx.xxx

# ---- EC2 IP (docker-compose.prod.yml用) ----
EC2_ELASTIC_IP=13.114.xxx.xxx
EOF
```

`13.114.xxx.xxx` を実際のElastic IPに置き換える。

**パスワードは強力なものを設定すること（英大小文字+数字+記号、16文字以上推奨）**

ファイルの権限を制限:
```bash
chmod 600 .env
```

---

### Task 5-3: Nginx設定ファイルをコピー

```bash
sudo cp nginx/nginx.conf /etc/nginx/conf.d/proposal-creation.conf
```

設定の文法チェック:
```bash
sudo nginx -t
```

期待出力:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf is successful
```

---

### Task 5-4: Dockerイメージをビルド・起動

```bash
cd ~/ProposalCreation

docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile full up -d --build
```

初回はDockerイメージのビルドに**5〜15分**かかる（Nextのビルドが重い）。

**進捗確認:**
```bash
docker compose logs -f --tail=50
```

`Ctrl+C` でログ表示を終了（コンテナは動き続ける）。

**コンテナ状態確認:**
```bash
docker compose ps
```

期待出力（全コンテナが `Up` または `healthy` であること）:
```
NAME                          STATUS
proposal-creation-backend     Up (healthy)
proposal-creation-frontend    Up (healthy)
proposal-creation-postgres    Up (healthy)
proposal-creation-neo4j       Up (healthy)
```

---

### Task 5-5: DBマイグレーション

```bash
docker compose exec backend alembic upgrade head
```

期待出力:
```
INFO  [alembic.runtime.migration] Running upgrade  -> xxxx, Initial migration
```

---

### Task 5-6: ナレッジデータの投入

> ローカルのNeo4jにナレッジデータが入っている場合は移行が必要。初回セットアップの場合はこのコマンドでロード。

```bash
docker compose exec backend python -m scripts.load_knowledge
```

データ量によっては数分〜数十分かかる場合がある。

---

### Task 5-7: Nginx起動

```bash
sudo systemctl start nginx
```

確認:
```bash
sudo systemctl status nginx
```

`Active: active (running)` であること。

---

### Task 5-8: 動作確認

**ヘルスチェック:**
```bash
curl http://localhost/api/health
```

期待出力:
```json
{"status":"ok"}
```

**ブラウザで確認:**

会社のネットワークに接続した状態でブラウザを開き:
```
http://13.114.xxx.xxx/
```

ProposalCreationのUIが表示されれば成功。

---

## Phase 6: 自動起動・停止設定

### Task 6-1: EC2操作用IAMロールを作成

> **目的:** EventBridge SchedulerがEC2を起動・停止するための権限を作成する。

**Step 1: IAMコンソールを開く**

サービス検索「IAM」→「ロール」→「ロールを作成」

**Step 2: ロールを設定**

```
信頼されたエンティティタイプ: AWSのサービス
ユースケース: 「Scheduler」（検索窓に入力）
→「EventBridge Scheduler」を選択 → 「次へ」
```

**Step 3: ポリシーをアタッチ**

「ポリシーを作成」をクリック（新しいタブで開く）

JSONタブを選択し以下を貼り付け:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:StartInstances",
        "ec2:StopInstances"
      ],
      "Resource": "arn:aws:ec2:ap-northeast-1:*:instance/*"
    }
  ]
}
```

- ポリシー名: `EC2StartStopPolicy`
- 「ポリシーを作成」

元のタブに戻り、作成した `EC2StartStopPolicy` を選択 → 「次へ」

**Step 4: ロール名を設定**

```
ロール名: EventBridgeEC2StartStopRole
```

「ロールを作成」

---

### Task 6-2: 起動スケジュール（平日 9:00）を作成

**Step 1: EventBridge Schedulerを開く**

サービス検索「EventBridge」→ 左メニュー「スケジューラ」→「スケジュールを作成」

**Step 2: スケジュールの詳細**

```
スケジュール名: proposal-creation-start
スケジュールグループ: default

スケジュールのパターン: 「定期スケジュール」
cron式: cron(0 0 ? * MON-FRI *)
  ↑ UTC 0:00 = JST 9:00 (UTC+9)

フレックスタイムウィンドウ: オフ
```

**Step 3: ターゲット**

```
ターゲットAPIを選択: 「すべてのAPIを参照」
  → 「EC2」→「StartInstances」を選択

インスタンスID: i-0123456789abcdef0（実際のインスタンスIDを入力）
```

JSON入力欄に:
```json
{
  "InstanceIds": ["i-0123456789abcdef0"]
}
```

**Step 4: アクション後の設定（実行ロール）**

```
実行ロール: 「既存のロールを使用」
→ EventBridgeEC2StartStopRole を選択
```

「スケジュールを作成」

---

### Task 6-3: 停止スケジュール（平日 19:00）を作成

Task 6-2 と同じ手順で:

```
スケジュール名: proposal-creation-stop
cron式: cron(0 10 ? * MON-FRI *)
  ↑ UTC 10:00 = JST 19:00

ターゲット: 「EC2」→「StopInstances」
```

```json
{
  "InstanceIds": ["i-0123456789abcdef0"]
}
```

---

## Phase 7: 最終動作確認

### Task 7-1: 全体動作テスト

**Step 1: 翌平日朝に自動起動を確認**

9:00過ぎにEC2コンソールでインスタンスが「実行中」になっていることを確認。

**Step 2: アプリへのアクセス確認**

会社のネットワークから:
```
http://13.114.xxx.xxx/
```

**Step 3: 社外ネットワーク（スマホのテザリング等）からアクセス不可を確認**

セキュリティグループが正しく機能しているか確認。
社外からアクセスするとタイムアウト（接続拒否）になればOK。

**Step 4: 19:00以降に自動停止を確認**

19:00過ぎにEC2コンソールでインスタンスが「停止済み」になっていることを確認。

---

## 運用メモ

### アプリの更新手順

コードを変更してデプロイする場合:

```bash
# EC2にSSH接続
ssh -i ~/.ssh/proposal-creation-key.pem ec2-user@13.114.xxx.xxx

cd ~/ProposalCreation

# 最新コードを取得
git pull origin main

# 再ビルド・再起動
docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile full up -d --build

# マイグレーション（スキーマ変更があった場合）
docker compose exec backend alembic upgrade head
```

### EC2が停止中に接続したい場合

AWSコンソールでインスタンスを選択 →「インスタンスの状態」→「開始」→ 起動後にSSH接続

### ログの確認

```bash
# 全サービスのログ
docker compose logs --tail=100

# バックエンドのみ
docker compose logs backend --tail=100 -f

# Nginx
sudo tail -f /var/log/nginx/error.log
```

### 会社のIPが変わった場合

AWSコンソール → EC2 → セキュリティグループ → `proposal-creation-sg` → インバウンドルールを編集 → 古いIPを新しいIPに変更

---

## セキュリティチェックリスト

- [ ] rootアカウントにMFA設定済み
- [ ] IAMユーザーにMFA設定済み
- [ ] セキュリティグループで会社IP以外のHTTPアクセスを遮断
- [ ] PostgreSQL/Neo4j Boltポートは外部非公開（127.0.0.1バインド）
- [ ] .envファイルのパーミッションが600
- [ ] .envがgitに含まれていない（.gitignoreで除外済み）
- [ ] 予算アラートを設定済み
