# Professional Writing Guide (Korean)

Notes to self (Claude) for writing Korean CVs (`cv/ko/*-cv.md`) and tailored
이력서 (`tailored-cvs/ko/*.md`) in this repo. Mirrors
`professional-writing-guide.md` with Korean-specific rules.

This guide is the source of truth for Korean-language materials. The English
guide still governs `cv/*.md`, `cover-letters/*.md`, and `website/` (English).

## Korean hiring convention

- 이력서 (resume) - **the** primary artefact. Typically tailored per
  application. Traditional layout: `인적사항`, `자기소개`, `경력사항`,
  `보유 기술`, `대표 프로젝트`, `학력사항`, `어학 능력`, `비고`.
- 자기소개서 (self-introduction essay) - answered in the employer's portal
  against company-specific prompts. Not produced in this repo.
- Free-form Western-style cover letters - NOT standard practice. The repo
  does not produce them for Korean listings.

## 존댓말 register

Use 하십시오체 / 합쇼체 - the formal written register with `-습니다` /
`-입니다` / `-하였습니다` endings. Never use 해요체 (`-예요`, `-이에요`)
in an 이력서 or CV.

- 귀사 ("your esteemed company") is the standard way to refer to the target
  company inside 자기소개. Do not use the company name repeatedly.
- Refer to the self as 저 (`저는 ...`), but drop the subject where natural -
  Korean business writing omits subjects freely.
- Use the posting's exact Korean phrasing for role titles (e.g.
  "시니어 안드로이드 개발자") rather than translating back from English.

## Keep internal-only details out

Same guardrails as the English guide. Do NOT include:

- 티켓 / 이슈 / 스토리 번호 (`JIRA-1234`, `#456`, `PROJ-789`)
- 스프린트 이름 또는 번호, 릴리스 트레인 식별자
- 외부에 공개된 적 없는 내부 프로젝트 코드명
- 브랜치명, 커밋 해시, PR 번호
- 업계 표준이 아닌 내부 도구명이나 약어
- 공개 인물이 아닌 내부 이해관계자 이름

## Write about impact instead

- 나쁨: "JIRA-1423 티켓을 완료하여 인증 모듈을 리팩터링했습니다."
- 좋음: "인증 모듈을 리팩터링하여 로그인 지연시간을 40% 단축했습니다."

- 나쁨: "Q3 스프린트 4에 FOO-22 에픽을 납품했습니다."
- 좋음: "12개 서비스를 신규 플랫폼으로 이관하는 분기 단위 이니셔티브를
  주도하여 일정 내 출시했습니다."

## Factual accuracy guardrails (identical to English guide)

### MDM 인증 시스템

MDM 인증 시스템은 **서버 측에서 구축된 시스템**입니다. Michael은
**디바이스 측 연동**만을 구현 - 포털 개발자가 구축한 서버 측 인증 API를
호출하는 Android 백엔드 및 Unity VR 클라이언트 코드.

- **쓰지 말 것**: "인증 시스템을 설계 및 구축", "조직 단위 인증 시스템을
  구축"과 같이 엔드투엔드 저작권을 암시하는 표현.
- **쓸 것**: "조직 단위 인증 시스템의 클라이언트 측/디바이스 측 연동을
  구현" 또는 "포털 개발자가 구축한 서버 측 API에 대응하는 클라이언트 측
  인증 플로우를 구축".
- 지원 로그인 모드(익명, ID 기반, 사용자명/비밀번호, SSO)는 백엔드가
  지원하는 모드 - Michael은 클라이언트에서 이를 소비. 로그인 모드는
  클라이언트 측 연동 맥락에서만 언급하고, 그가 설계한 모드로 표현하지 말 것.

### MDM 원격 앱 설치 / ADB

ADB는 Windows 프로비저닝 도구를 통한 기기 **등록(enrollment)** 용도로만
사용됩니다. ADB는 원격 앱 설치 메커니즘이 **아닙니다**. 원격 앱 설치를
ADB와 연결하여 작성하지 말 것.

## PDF 빌드 및 글꼴

`cv/ko/*-cv.md` 파일은 `.github/workflows/build-cvs.yml`에서 pandoc +
xelatex + Noto Serif CJK KR로 매 main 푸시마다 PDF로 빌드됩니다.
`tailored-cvs/ko/*.md` 파일은 자동 빌드 대상이 아니며, 지원 페이지
(`website/apply.html`)의 "Download as PDF" 버튼(브라우저 인쇄)을 통해
변환됩니다.

- 한글 및 한자 문자 사용 가능 (영문 CV의 ASCII 전용 규칙 미적용).
- 이 예외는 `cv/ko/CLAUDE.md` 및 `tailored-cvs/ko/CLAUDE.md`에 명시되어
  있습니다.

## 이력서 레이아웃 (standard Korean developer resume format)

The fixed structure follows the Jumpit/standard Korean developer resume format
(schema defined in `tailored-cvs/ko/CLAUDE.md`):

**이름**: 정강서 (Michael Evans) — always use this form in Korean 이력서.

1. `# 정강서 (Michael Evans)` heading + **직무명** subtitle
2. Personal info table — Email / 포트폴리오 / 국적 / 거주지 / 비자
3. `## 소개 / About Me` — 4 bullet points (not a paragraph), strengths tailored to posting
4. `## 기술스택 / Skill Set` — table with 구분 / Skill rows, reordered per posting
5. `## 경력 사항 / Work Experience` — summary table: 재직기간 | 회사명 | 부서/직급 | 담당업무
6. `## 주요 프로젝트 / Projects` — per company (numbered, latest first); each project
   uses a detail table: 사용언어 및 개발환경 | 인력구성 및 기여도 | 주요업무 및 상세역할 | 성과/결과 | 참고자료
7. `## 기타 사항` — subsections: 학력, 어학, 기타 (posting-specific notes)

## Quick checklist before saving

1. 모든 레퍼런스를 회사 외부 독자도 이해할 수 있는가?
2. 각 경력사항 bullet이 프로세스 부산물이 아닌 임팩트/범위/역량을 기술하고
   있는가?
3. 모든 티켓 ID, 스프린트 태그, 내부 코드명을 제거했는가?
4. 모든 사실 기반 주장이 위의 가드레일과 일치하는가?
5. 존댓말(-습니다)로 일관되게 작성되었는가?
6. 공고에 명시된 핵심 기술 스택이 `보유 기술` 테이블의 상단에 배치되어
   있는가?
7. HTML 주석으로 기반 CV 및 jobId가 명시되어 있는가? (`<!-- base: ... -->`, `<!-- jobId: ... -->`)
8. 이름이 `정강서 (Michael Evans)` 형식으로 표기되어 있는가?

하나라도 "아니오"라면 커밋 전에 수정.
