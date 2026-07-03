# 시드 용어집 — 용어 선정 결정 기록 (Seed Glossary Term Decisions)

> **상태: 확정·동결(frozen).** 규칙은 [BR-S4](business-rules.md#br-s4--용어집-적용-91--q8a), 구현은
> `domain/glossary.py`(`SEED_KEEP_AS_IS` / `SEED_MAPPINGS`).
> 공유 시드는 사전이 아니라 **모든 요약·번역 프롬프트에 실리는 거버넌스 산출물**이다. 근거로 한 번
> 확정하고 동결하며, 개인 취향 롱테일은 **개인 용어집**(개인 강한/약한 용어)이 흡수한다.

## 1. 방법론

- 용어를 임의 선정하지 않고, 프로젝트가 다루는 분야(ML/DL/NLP·arXiv 논문)에서 **실제로 널리 쓰이는
  표기**를 조사해 근거와 함께 등급화했다.
- **공신력 있는 단일 한국어 AI 용어 카논은 존재하지 않는다**(국립국어원 = 종합 AI 목록 없음·일부
  다듬은 말만; TTA = AI 용어사전·표준이 있으나 항목별). 따라서 대부분 등급은 **"사실상 만장일치 관행"**
  이며, `A`는 de jure 표준이 아니라 **위키백과 표제어 + 표준 교재 + 주요 벤더 한글 문서가 거의
  일치**함을 뜻한다.

## 2. 근거 등급 (4단계)

| 등급 | 의미 | 처리 |
|---|---|---|
| **A** | 공신력 표준 또는 사실상 만장일치 관행 | 채택 가능(단, 아래 "강제 실익" 필터 적용) |
| **B** | 국내 연구실·교재에서 매우 널리 쓰임(소수 변형 병존) | 채택 가능 |
| **C** | 번역 혼재 | **보류(시드 제외)** |
| **D** | 논란 크거나 문맥 의존 | **제외** |

## 3. 선정 규칙 (결정 함수)

```
keep-as-is(영어 유지):  고유 모델·아키텍처명·약어 (BERT, LoRA, RLHF, GAN, SGD…)
                        → 번역 시 음차·오역 위험 + 원문 대조 필요. 규칙으로 정당화되므로
                          자명한 이름은 등급 없이 등재 가능.
강한 매핑(prompt_enforced): 등급 ∈ {A,B}  AND  강제 실익 있음(음차 개념어로 LLM이
                          엉뚱한 한국어로 오번역할 위험)  AND  고빈도
                          → A-자명어(신경망·역전파…)는 실익 없어 제외(프롬프트만 비대)
C(혼재) → 보류(제외 또는 keep-as-is로 우회)
D(논란) → 제외
```

**핵심:** 강한 매핑은 "LLM이 틀릴 위험이 있는" 것만 넣는다. `attention→'주의'`, `embedding→'매장'`
같은 **그럴듯한 오번역**을 막는 게 목적이다. 이미 LLM이 정확히 뽑는 A-자명어를 넣으면 프롬프트만
길어지고(비용) 이득이 없다.

## 4. 확정 시드

### 4.1 강한 매핑 (`SEED_MAPPINGS`, prompt_enforced) — 오번역 위험 음차 개념어만

| 용어 | 채택 | 오번역 위험 | 등급 |
|---|---|---|---|
| attention | 어텐션 | 높음('주의/주목') | B |
| embedding | 임베딩 | 높음('매장/삽입') | B |
| latent space | 잠재 공간 | 낮음 — **일관성 위해 강제(예외)** | B |

> **latent space 예외 근거(§3 규칙 명시적 예외):** 개별 오번역 위험은 낮지만(대개 '잠재 공간'으로 무난히
> 번역됨), attention·embedding과 함께 생성모델 핵심 음차 개념어 3종의 **표기 일관성**을 위해 강제에 포함한다.
> 즉 이 항목은 "고빈도 오번역 위험"이 아니라 "일관성"이 채택 사유다 — §3의 위험-기반 규칙을 문자 그대로
> 적용해 제거하지 말 것.

경계 부류(음차 개념어)를 전수 점검한 결과, **강제 대상은 위 3개가 전부**다(attention·embedding=오번역
위험, latent space=일관성 예외). `self-attention`은
attention이 강제되면 자동으로 따라오고(셀프 어텐션), `token·prompt·tokenization·encoder/decoder`는
LLM이 이미 음차하며, `inference·hallucination`은 정번역이라 강제 불필요.

### 4.2 영어 유지 (`SEED_KEEP_AS_IS`)

고유 모델·아키텍처명·약어·지표. 규칙으로 등재(개별 등급 불요):

- **아키텍처/모델:** Transformer, BERT, GPT, T5, BART, RoBERTa, CLIP, ViT, ResNet, U-Net, CNN,
  RNN, LSTM, MLP, GAN, VAE, GNN, MoE, LoRA, RAG
- **학습/정렬 기법:** fine-tuning, RLHF, SFT, PPO, DPO, PEFT
- **약어/활성/옵티마이저:** LLM, SOTA, ReLU, Adam, SGD
- **데이터셋/지표:** ImageNet, BLEU, ROUGE, F1, AUC, IoU

> "왜 LoRA는 영어인데 latent space는 번역?" → **규칙**: 고유 모델명·약어는 영어 유지, 일반 개념어는
> A/B 표준 번역. LoRA=고유 기법명(영어), latent space=일반 개념어(표준 번역 존재).

## 5. 조사한 매핑 후보 — A/B/C/D 등급표

| 용어 | 채택 후보 | 등급 | 근거 요지 | 시드 |
|---|---|---|---|---|
| neural network | 신경망 | A | 위키 표제어·전 교재 만장일치 | ❌ A-자명(LLM 정확) |
| backpropagation | 역전파 | A | 교재 표제어·만장일치 | ❌ A-자명 |
| overfitting | 과적합 | A | 압도적(과대적합 소수) | ❌ A-자명 |
| activation function | 활성화 함수 | A | 교재 표준 | ❌ A-자명 |
| gradient descent | 경사 하강법 | A | IBM 한글·나무위키 표제어 | ❌ A-자명 |
| supervised learning | 지도 학습 | A | 위키·NVIDIA·교재 | ❌ A-자명 |
| reinforcement learning | 강화 학습 | A | 만장일치 | ❌ A-자명 |
| transfer learning | 전이 학습 | A | 위키 표제어·appen·MathWorks | ❌ A-자명 |
| weight | 가중치 | A | 만장일치 | ❌ A-자명 |
| quantization | 양자화 | A | ETRI·교재 만장일치 | ❌ A-자명 |
| loss function | 손실 함수 | B | 표준이나 cost=비용함수와 문맥 혼용 | ❌ A/B-자명 |
| unsupervised learning | 비지도 학습 | B | 우세하나 '자율 학습' 병존 | ❌ A/B-자명 |
| inference | 추론 | B | 우세하나 '인퍼런스' 병존 | ❌ 정번역·LLM 정확 |
| tokenization | 토큰화 | B | 관행 확립 | ❌ LLM 이미 음차 |
| encoder / decoder | 인코더 / 디코더 | B | 음차가 사실상 표준 | ❌ LLM 이미 음차 |
| hallucination | 환각 | B | 학회(KIPS)·업계 우세('할루시네이션' 병존) | ❌ 정번역·LLM 정확 |
| **attention** | **어텐션** | **B** | 음차 관행 압도적('주의/주목' 오번역 위험) | ✅ |
| **embedding** | **임베딩** | **B** | 음차 압도적('매장/삽입' 오번역 위험) | ✅ |
| **latent space** | **잠재 공간** | **B** | 우세(띄어쓰기 변형만) | ✅ |
| fine-tuning | 파인튜닝 / 미세조정 | **C** | 둘 다 매우 흔함 → **keep-as-is로 강등** | ➡️ 영어 유지 |
| gradient(단독) | 기울기 / 그래디언트 | **C** | 혼재(수학 뿌리 vs DL 실무) | ❌ 보류 |
| regularization | 정칙화/규제/정규화 | **D** | 4갈래 + normalization(정규화)과 충돌 | ❌ 제외 |

## 6. 캐시 영향 (SEED_VER)

시드 확정으로 `SEED_MAPPINGS`(fine-tuning 제거)·`SEED_KEEP_AS_IS`(보강)가 바뀌어 `SEED_VER`가
`344c3ccb`(동결 baseline) → `ba6f5f2e`로 **의도적으로 divergence**한다. 경로에 `_s{seedVer}` 세그먼트가
활성화되어 **직전 시드 기반 요약·번역이 자동 무효화**된다(다시 열람되는 것만 지연·주문형 재생성).
현재 요약/번역 캐시 코퍼스가 거의 비어 있어 **재생성 비용 ≈ 0**. `_SEED_BASELINE_VER`는 동결
마커이므로 **갱신하지 않는다**(갱신 시 무효화가 무력화됨).

## 7. 출처

- gradient — [AI/ML 사전(변형 나열)](https://wikidocs.net/204828) · [기울기(벡터) 위키](https://ko.wikipedia.org/wiki/%EA%B8%B0%EC%9A%B8%EA%B8%B0_(%EB%B2%A1%ED%84%B0))
- gradient descent — [IBM 한글](https://www.ibm.com/think/topics/gradient-descent) · [AI/ML 사전](https://wikidocs.net/120156)
- regularization — [AI/ML 사전](https://wikidocs.net/120052) · [Normalization/Regularization 구분](https://realblack0.github.io/2020/03/29/normalization-standardization-regularization.html)
- convolution/backpropagation — [역전파 교재](https://wikidocs.net/37406) · [합성곱 위키](https://ko.wikipedia.org/wiki/%ED%95%A9%EC%84%B1%EA%B3%B1)
- 학습 방식 — [비지도 학습 위키](https://ko.wikipedia.org/wiki/%EB%B9%84%EC%A7%80%EB%8F%84_%ED%95%99%EC%8A%B5) · [전이학습 위키](https://ko.wikipedia.org/wiki/%EC%A0%84%EC%9D%B4%ED%95%99%EC%8A%B5)
- quantization — [경량 딥러닝 동향(ETRI)](https://ettrends.etri.re.kr/ettrends/176/0905176005/34-2_40-50.pdf)
- hallucination — [환각 억제 평가(KIPS)](https://koreascience.kr/article/CFKO202532436090641.page)
- embedding — [한국어 임베딩(ratsgo)](https://github.com/ratsgo/embedding)
- 표준화 기관(카논 부재 확인) — [국립국어원 다듬은 말](https://www.korean.go.kr/front/imprv/refineList.do?mn_id=158) · [TTA 정보통신용어사전 '인공지능'](https://terms.tta.or.kr/dictionary/dictionaryView.do?subject=%EC%9D%B8%EA%B3%B5%EC%A7%80%EB%8A%A5)
