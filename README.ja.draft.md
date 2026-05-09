>Extension for Claude Code/Long Context Tree - Made by Ryosuke Kawai
> Claude Codeにおいて計量モデルを呼び出すことで過去のセッションを忘れずに高精度な会話を実現する。

> ⚠️ **特許出願済み（日本国内、2026年）**。
> 商用利用（製品への組込、SaaS化、再配布、有償サービスでの提供等）を
> 検討される場合は、事前に [@rkcevE](https://x.com/rkcevE) の DM
> または GitHub Issues までご連絡ください。
> 個人利用・フリーランス業務での使用・社内検証に制限はありません。

<!--
編集方針
========
- 角括弧 [...] のあるセクションは要確認・要編集の箇所です。
- 日本語版を確定させた後、英訳して README.md にする予定です。
- patent セクションの文言は中原弁理士の確認が必要です。
-->

---

## 1. このプロジェクトが解決する問題

Claude Code を含む長文対話システムには共通の問題があります。

- セッションが長くなると過去の文脈が自動圧縮で失われ、議論の根底がブレる
- セッションを切り替えると以前の議論を再説明する必要が生じる
- 重要な技術判断（採用したアーキテクチャ、却下した案、未解決の課題）が会話履歴に埋もれる

`claude-code-cms` は、毎ターンの会話を**構造化された相関図**としてローカル ディスクに保存し、次のターン開始時に関連する事実だけを抽出してモデルに注入することで、これらの問題を解決します。

---

## 2. 何をするコードか

2つのフックが Claude Code の `settings.json` に登録され、各ターンで自動発火します。

| フック | タイミング | 役割 | 使用モデル |
|---|---|---|---|
| `Stop` フック | あなたへの応答完了直後 | 直近の往復を読み、相関図に新しい情報を追加（または既存ノードの mass を加算） | Claude Sonnet 4.6 |
| `UserPromptSubmit` フック | あなたが新しいプロンプトを送信した瞬間 | 既存の相関図と新プロンプトを照合し、関連する事実 3〜5 個を抽出 | Claude Haiku 4.5 |

抽出された事実は `additionalContext` として Opus 主セッションのコンテキストに前置注入されます。Opus 自身は何が起きているか意識する必要がなく、ただ「自然と関連事実を覚えている」状態になります。

---

## 3. 相関図の構造

[論文 (DOI: 10.5281/zenodo.19354705)](https://doi.org/10.5281/zenodo.19354705) にもとづくツリー構造です。

```
SUN: トピック（議論の最上位概念）
├── PLANET (mass=N): サブトピック（議論の柱、深さ N）
│   ├── SAT: 詳細事実
│   └── SAT: 詳細事実
└── PLANET (mass=N): 別のサブトピック
    └── SAT: ...
```

各惑星ノードの **質量 (mass)** は「その惑星の下に蓄積された衛星ノードの数」に対応し、議論の深さを表します。`UserPromptSubmit` フックは質量の高い惑星を優先的に注入候補とすることで、ユーザーの長期的なこだわりを忘れない設計になっています。

---

## 4. 動作の流れ

```
[ユーザー入力]
    │
    ↓
[UserPromptSubmit フック発火]
    │  Haiku 4.5 が相関図と新入力を読み、関連事実を抽出
    ↓
[additionalContext として Opus に注入]
    │
    ↓
[Opus 主セッションが応答生成]
    │
    ↓
[Stop フック発火]
    │  Sonnet 4.6 が直近往復を読み、相関図 JSON を更新
    ↓
[correlation_map.json をディスクに保存]
```

両フックは別プロセスとして起動するサンドボックス環境で動くため、`Opus` 主作業の応答性に大きな影響はありません

---

## 5. インストール

### 必要環境

- Python 3.11 以上
- Claude Code CLI（VS Code 拡張または npm 版）
- Claude Pro / Max サブスクリプション、または Anthropic API key

### 手順

**Linux / macOS / Git Bash:**

```bash
git clone https://github.com/rkceve/claude-code-cms.git ~/.claude/hooks/cms
cd ~/.claude/hooks/cms
python3 install.py    # Python 3.11+ が必要
```

**Windows (PowerShell):**

```powershell
git clone https://github.com/rkceve/claude-code-cms.git "$HOME\.claude\hooks\cms"
cd "$HOME\.claude\hooks\cms"
python install.py     # Python 3.11+ が必要
```

インストーラは `~/.claude/settings.json` の `hooks` セクションに必要な2行を冪等的に追加します。既存のフックは上書きしません。

### 確認

```bash
python install.py --status
```

両フックが登録されていれば成功です。新しい Claude Code セッションを起動すると自動的に動き出します。

### アンインストール

```bash
python install.py --uninstall
```

---

## 6. 使い方

インストール後は何もする必要がありません。普段通りClaude Codeでやり取りすると、相関図が自動的に蓄積されていきます。

### 相関図の所在

```
~/.claude/projects/<cwd-slug>/memory/cms/correlation_map.json
```

`<cwd-slug>` はプロジェクト ディレクトリのパスを変換した文字列です。プロジェクトごとに自動的に分離されます。

### 動作ログ

```
~/.claude/hooks/cms/cms.log
```

各フック呼び出しの結果が時刻付きで記録されます。容量超過時は自動ローテーションされます。

### 一時的な無効化

特定のセッションだけフックをスキップしたい場合:

```bash
CMS_DISABLE=1 claude
```

---

## 7. 設定

`cms.toml.example` を `cms.toml` にコピーして編集することで、以下が変更できます。

- 使用モデル（Haiku/Sonnet以外への切替）
- タイムアウト
- リトライ回数
- 除外したいプロジェクトパターン（glob形式）
- 相関図のサイズ上限（古い低mass惑星の自動削減）
- プロバイダモード（CLI subprocessまたはAnthropic SDK直叩き）

詳細はファイル内のコメントを参照してください。

---

## 8. 運用コスト

各往復で2回のモデル呼出（Haiku1回 + Sonnet1回）が発生します。

基本的にこのシステムはclaude Pro/Maxのトークンを消費して動きます。API keyの別途準備は不要です。。Haiku/Sonnet は軽量なので Opus 主作業を圧迫することは少ないですが、1往復ごとに追加のトークンは消費するので、ご注意ください。節約したい場合は `cms.toml` で除外パターンを設定するか、軽い相談時のみ `CMS_DISABLE=1` を使ってください。

---

## 9. 既知の制限

### Claude Code CLI のバグへの暫定対応

Claude Code v2.1.x の `claude -p --no-session-persistence` フラグは、システム プロンプトが大きい場合に**無視されて転写ファイルが書き込まれる**バグがあります。これにより VS Code 拡張のチャット タブが大量生成されるのを防ぐため、本実装は内部で**専用サンドボックス cwd** で `claude -p` を起動し、書き込まれた転写を即座に削除しています。Anthropic 側で修正されたら不要になる暫定対応です。

### スキーマ違反のデータ廃棄

Sonnet4.6は稀に独自キー（`label`、`description` など）を使ったJSONを返すことがあります。本実装は厳格なスキーマ検証を行い、違反した場合は更新を**破棄**します（既存マップを保護）。結果として、その往復分の相関図更新は行われません。次の往復で正常な応答が返れば追いつきます。

### per-project 分離の前提

現在のcwdを基準にプロジェクトを識別します。同じ作業を別ディレクトリから始めると別の相関図になります。VS Codeで開いているフォルダを切り替えた場合は注意してください。

### API key モードは未検証

`provider.mode = "anthropic_sdk"` 経路は実装されていますが、開発者個人の環境では API key を使った実機検証ができていません。動作報告と issue 報告を歓迎します。

---

## 10. プライバシー

相関図には**会話の要約が平文 JSON で保存**されます。以下の点に注意してください。

- `correlation_map.json` を**バージョン管理に含めない**こと（`.gitignore` 推奨）
- 機微情報（API キー、認証情報、個人情報）を含む会話を行った後は手動で当該ノードを削除するか、`correlation_map.json` を削除して相関図を作り直すこと
- このプロジェクトはネットワーク経由で外部サーバーへ会話内容を送信しません（Anthropic API 経由のモデル呼出を除く）

---

## 11. 開発者について

**Ryosuke Kawai** — 独立研究者（15歳）。

- X / Twitter: [@rkcevE](https://x.com/rkcevE)
- 連絡先: X の DM、GitHub Issues、または `ryosukekawai1224@gmail.com`

主な研究分野:

- **画像処理**: 構造グラフ データ (SGD) を用いたエッジ ベクトル + 内部ラスター + ONNX 超解像のハイブリッド圧縮
- **VR**: 3DGS と sEMG (表面筋電図) による 6DoF 視点予測、未来予測リプロジェクションによる VR 酔い低減
- **LLM**: 質量加算アテンション (mass-aware attention bias) による長文脈の文脈崩壊抑止

---

## 12. 特許との関係

このプロジェクトは、論文「[Geometric Convergence for Conversational Context Management: A Distributed Structured Memory Architecture Based on Correlation-Diagram Data](https://doi.org/10.5281/zenodo.19354705)」（DOI: `10.5281/zenodo.19354705`）に記載される技術を、Claude Code のフック機構を用いて参考実装したものです。

### 含まれている要素

- ローカル デバイスにおける相関図データの作成と更新
- 太陽ノード / 惑星ノード / 衛星ノードによるツリー構造化
- 評価部による整合性維持（本実装ではスキーマ検証で簡略化）

### **含まれていない要素**

- 質量加算アテンション機構（wM 項）は実装されていません。これはモデル内部のアテンション スコア計算への介入を必要とするため、Claude Codeでは原理的に実装不可能です。当該機構は別の実装（Gemma + LoRA への直接パッチ）で実現される予定で、このリポジトリの範囲外です。


---

## 13. ライセンス

このリポジトリのソース コードは **MIT License** で公開されています（[LICENSE](./LICENSE) ファイル参照）。

ただし、本実装が依拠する技術は**特許出願済み**です。MIT License は
ソース コードの利用権のみを付与し、特許権のライセンスは含みません。

| 利用形態 | 制限 |
|---|---|
| 個人利用・学術研究・教育目的 | なし |
| フリーランスが受託業務で使用 | なし |
| 社内検証・社員の生産性ツールとして利用 | なし |
| 製品への組込、SaaS 化、再配布、有償サービスでの提供 | 事前にライセンス相談 |

商用利用に関する問い合わせは [@rkcevE](https://x.com/rkcevE) の DM、または
GitHub Issues までご連絡ください。

---

## 14. 引用

研究または学術的な文脈でこの実装を参照する場合、以下の形式での引用を歓迎します。

このリポジトリの実装を引用する場合:

```bibtex
@misc{kawai2026cms,
  author    = {Kawai, Ryosuke},
  title     = {claude-code-cms: A reference implementation of structured
               conversation memory for Claude Code},
  year      = {2026},
  publisher = {GitHub},
  url       = {https://github.com/rkceve/claude-code-cms}
}
```

理論的背景となる論文を引用する場合:

```bibtex
@misc{kawai2026geometric,
  author    = {Kawai, Ryosuke},
  title     = {Geometric Convergence for Conversational Context Management:
               A Distributed Structured Memory Architecture Based on
               Correlation-Diagram Data},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.19354705},
  url       = {https://doi.org/10.5281/zenodo.19354705}
}
```
---

## 15. 謝辞

- **Anthropic** — Claude Code CLI および Claude Sonnet / Haiku の提供

---

## 16. 貢献

Issue 報告と Pull Request を歓迎します。特に以下の領域での協力を求めています。

- API key モード（`anthropic_sdk` プロバイダー）の実機検証
- Linux / macOS でのテスト
- 上記の論文に対して共同研究をしてくださる企業がいれば連絡お願いします。

