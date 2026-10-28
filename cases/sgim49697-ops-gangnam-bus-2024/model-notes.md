# 모델 구현과 재현 범위

이 사례는 서로 다른 모델을 같은 시간 분할·실측 정답·평가 키에서 비교한다. 아래 원저자의 논문 성능을 재현했다고 주장하지 않는다. 모델 학습과 정책 효과 추정은 별개다.

| 모델 | 구현·출처 | 이 사례의 선택 |
|---|---|---|
| 세 단순 기준선 | 개인 코드 | 마지막 완료 구간, 목표시각의 168시간 전, 학습기간 요일시간 평균 |
| CatBoost | [공식 프로젝트](https://github.com/catboost/catboost), Apache-2.0 | CPU, 1·3시간 각각 직접 회귀. 과거 lag·이동 통계·관측 마스크·달력·링크 ID |
| DLinear | [원 논문 구현](https://github.com/cure-lab/LTSF-Linear), [NeuralForecast](https://github.com/Nixtla/neuralforecast), Apache-2.0 | NeuralForecast 3.3.0 네트워크의 이동평균 분해·선형 출력 |
| PatchTST | [원 논문 구현](https://github.com/yuqinie98/PatchTST), NeuralForecast, Apache-2.0 | 168 입력·3 출력, patch 12·stride 6, encoder 2·heads 4 |
| Chronos2 | [공식 모델](https://huggingface.co/amazon/chronos-2), [공식 코드](https://github.com/amazon-science/chronos-forecasting), Apache-2.0 | revision 고정, 중앙값, zero-shot, 서로 다른 발행시각 간 cross-learning 비활성화 |
| DCRNN | [원 논문 구현](https://github.com/liyaguang/DCRNN), MIT | 개인 PyTorch 구현. 정·역방향 random walk 2단계, 확산 GRU encoder/decoder 2층, 자기회귀 3시간 출력 |
| STGCN | [원 논문 구현](https://github.com/VeritasYin/STGCN_IJCAI-18), BSD-2-Clause | 개인 PyTorch 구현. 대칭화·정규화 라플라시안, Chebyshev K=3, 시간 GLU 2블록, 마지막 시간 표현의 직접 출력 |

DCRNN·STGCN 코드를 원 저장소에서 복사하거나 TensorFlow 구버전을 설치하지 않았다. 구조를 참고한 교육용 구현이며, DCRNN의 curriculum learning 등 원 논문의 모든 학습 장치를 재현하지 않는다. 지도상 가까운 링크를 임의로 연결한 그래프를 실제 실험에 쓰지 않는다.

NeuralForecast의 네트워크 `forward`를 사용하고 일반 PyTorch 학습 루프에서 손실·창·조기 종료를 관리한다. 세 출력이 모두 실측인 창만 학습한다. 입력 결측 마스크는 보존하여 창 선택·CatBoost·그래프 모델에 사용한다. DLinear·PatchTST·Chronos2는 인과적으로 채운 속도 입력을 사용하며 별도 마스크 채널을 지원한다고 주장하지 않는다. 표준화는 학습 구간에서만 맞추고, 검증 시 원래 km/h로 되돌려 1시간 MAE를 선택 기준으로 쓴다.

## 장비 검증과 실험 기록

WSL의 Python 3.12.12, NVIDIA RTX 5070 Ti(연산 능력 12.0, 드라이버 610.88)에서 PyTorch 2.13.0/cu130·`sm_120`·BF16 행렬 연산을 확인했다. 현재 인터프리터의 `Python.h`·`pyconfig.h`가 존재했고 native JIT를 끄지 않았다. 정확한 설치 목록은 [requirements-gpu.lock](requirements-gpu.lock)에 남겼다. 다른 장비에서는 같은 CUDA 인덱스를 무조건 사용하지 않는다.

2026-10-28 합성자료 점검에서 단순 기준선 3개, CatBoost, DLinear·PatchTST 각 100 step, DCRNN·STGCN 각 2 step의 학습·저장·재로딩·추론, Chronos2 고정 revision 추론이 통과했다. 합성 입력이므로 이 기록을 실제 데이터의 성능이나 처리량으로 해석하지 않는다. 그래프 점검도 합성 연결표만 사용했으며 역사적 그래프 확보를 대신하지 않는다.

실제 실행에서는 선택한 설정, 세 seed, 학습·추론 시간, OOM 재시도, 최대 VRAM, 신경망 파라미터 수, CatBoost 트리 수, 평가 키 수를 `runs/<실험명>/`에 남긴다. 실행 폴더는 덮어쓰지 않는다. Chronos2의 외부 사전학습 데이터와 평가기간 중첩 여부는 미확인으로 표시한다.
