# 나만의 스킬 만들기

`workflow-template.md` 에서 채운 다섯 칸을 스킬 파일로 옮겨요.

## 1. 초안 만들기 → 스킬 자리로 옮기기
1. 초안: `workspace/skill-drafts/<스킬 이름>/SKILL.md` — ROY에게 「이 템플릿으로 내 스킬 초안 만들어줘」라고 하면 돼요.
2. 옮기기: 스킬은 `.claude/skills/<스킬 이름>/SKILL.md` 에 있어야 Claude Code가 알아봐요.
   Claude Code가 이 폴더에 쓸 때 허락을 물으면 **허용**. 막히면 입력창에 이렇게 치세요 (맨 앞 `!` 는 터미널 명령):
   ```
   ! mkdir -p .claude/skills/<스킬 이름> && cp workspace/skill-drafts/<스킬 이름>/SKILL.md .claude/skills/<스킬 이름>/
   ```
- 이름은 **`my-` 로 시작**하고 영문 소문자와 `-` 만 (예: `my-competitor-check`). `my-` 로 시작하는 스킬은 GitHub에 올라가지 않게 막혀 있어요.
- 다른 사람과 나누고 싶으면 → [`../shared-rules/README.md`](../shared-rules/README.md)

## 2. 아래를 복사해서 채우기

```markdown
---
name: my-<스킬 이름>
description: <무엇을 하는 스킬인지 한 문장>. 「<이렇게 말하면>」「<이렇게 말해도>」에 쓴다. <입력>을 받아 <결과물>을 workspace/reports/ 에 저장한다.
---

# <스킬 제목>

## 입력 데이터
- <무엇을 · 어디서 · 어떤 형식으로>
- 없으면 이렇게 묻는다: 「<질문>」

## 처리 순서
1. <단계>
2. <단계>
3. 저장 — `workspace/reports/<스킬 이름>-YYYY-MM-DD.md`

## 판단 기준
- <기준 — 숫자로 쓸 수 있으면 숫자로>
- ⛔ <하지 말아야 할 것 — 예: 원인을 단정하지 않는다>

## 결과물 형식
(보고서의 칸 순서를 그대로 적기)
```

## 3. 잘 쓰는 법
- **description 이 제일 중요해요.** Claude Code는 이 한 문장을 보고 언제 이 스킬을 쓸지 정해요. 「언제 쓰는지」와 「무엇을 내놓는지」를 꼭 넣으세요.
- 처리 순서는 **번호**로. 순서가 있어야 매번 같은 절차로 돌아요.
- 결과물 형식은 **칸 이름까지** 정해 두세요.
- 숫자 계산이 들어가면 AI가 매번 계산하게 두지 말고, 이 킷의 `tools/ads_check.py` 처럼 **계산만 하는 작은 도구**를 두는 게 좋아요. ROY에게 「이 계산을 도구로 만들어줘」라고 해 보세요.

## 4. 돌려 보기
Claude Code에서 description 에 적은 말로 불러 보세요. 결과가 마음에 안 들면 **스킬 파일을 고치고** 다시 돌려요 — 프롬프트를 다시 쓰는 게 아니라.

## 5. 다음
- 스킬 두 개를 이어 보기 — 예: 「광고 성과 점검」에서 가장 크게 떨어진 광고를 「소재 분석」에 넘기기 → [`../docs/roy-workflow.md`](../docs/roy-workflow.md)
- 다른 마케터에게도 쓸모 있으면 공유하기 → [`../shared-rules/README.md`](../shared-rules/README.md)
