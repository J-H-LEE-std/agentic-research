import numpy as np
import json
import os
from scipy.stats import norm
import time

# 고정 랜덤 시드
np.random.seed(42)

# 하이퍼파라미터 설정
N = 10          # 인구 크기 (줄임)
D = 3           # 차원 수 (줄임)
T = 5           # 최대 세대 수 (줄임)
B_total = 100   # 총 평가 예산 (줄임)
δ_total = 0.1   # 전체 false-negative 허용 확률
R_max = 2       # 최대 평가 라운드 수 (줄임)
C_full = 10     # full 평가 비용 (cheap 샘플 수 기준)
C_cheap = 1     # cheap 평가 비용
p_audit = 0.05  # 감사 확률 (줄임)
margin_margin = 0.01  # 제거 마진
safety_factor = 2
λ_0 = 1.0       # 초기 라그랑지 승수
η_λ = 0.05      # 라그랑지 승수 업데이트 속도
F_0 = 0.8       # 초기 돌연변이 계수
CR_0 = 0.9      # 초기 교차율
α = 0.5         # F 감쇠 계수
β = 0.5         # CR 감쇠 계수
CR_min = 0.1    # 최소 CR
ε = 0.1         # Hoeffding 경계 ε
[a, b] = [0, 10]  # 평가 함수의 범위

# EAR-DE 알고리즘 구현
def EAR_DE():
    # 초기 인구 생성
    P = np.random.rand(N, D) * 10  # [0, 10] 범위
    
    # 초기 full 평가
    full_fitness = [full_eval(x) for x in P]
    
    # 서로게이트 모델 초기화 (sklearn 없이 단순한 모델 사용)
    class SimpleSurrogate:
        def __init__(self):
            self.X_train = None
            self.y_train = None
            
        def fit(self, X, y):
            self.X_train = X.copy()
            self.y_train = y.copy()
            
        def predict(self, X):
            # 단순한 k-NN 예측 (k=3)
            if self.X_train is None:
                return np.zeros(len(X))
            
            predictions = []
            for x in X:
                distances = np.linalg.norm(self.X_train - x, axis=1)
                k = min(3, len(distances))
                nearest_indices = np.argpartition(distances, k-1)[:k]
                prediction = np.mean(self.y_train[nearest_indices])
                predictions.append(prediction)
            return np.array(predictions)
    
    surrogate_model = SimpleSurrogate()
    
    # 초기 학습 데이터
    X_train = P.copy()
    y_train = np.array(full_fitness)
    surrogate_model.fit(X_train, y_train)
    
    λ = λ_0
    F = F_0
    CR = CR_0
    
    results = {
        "generations": [],
        "best_solution": None,
        "best_fitness": -np.inf
    }
    
    for gen in range(T):
        start_time = time.time()
        
        # 자식 생성
        Q = []
        for i in range(N):
            # DE/rand/1/bin
            indices = [j for j in range(N) if j != i]
            a_idx, b_idx, c_idx = np.random.choice(indices, 3, replace=False)
            v = P[a_idx] + F * (P[b_idx] - P[c_idx])
            v = np.clip(v, 0, 10)  # 경계 처리
            
            # 교차
            jrand = np.random.randint(0, D)
            u = np.zeros(D)
            for j in range(D):
                if np.random.rand() < CR or j == jrand:
                    u[j] = v[j]
                else:
                    u[j] = P[i][j]
            Q.append(u)
        
        # EAR 스테이지
        # 초기화
        candidates = []
        for q in Q:
            candidates.append({
                'x': q,
                'm': 0,
                'sum': 0,
                'mean': 0,
                'status': 'alive',
                'samples': []
            })
        
        # 라운드별 샘플링
        δ_per_comparison = δ_total / (N * R_max * safety_factor)
        m_r_base = int(((b - a)**2 / (2 * ε**2)) * np.log(2 / δ_per_comparison))
        
        alive = [c for c in candidates if c['status'] == 'alive']
        survivors = []
        
        for r in range(R_max):
            if not alive:
                break
                
            # 샘플링
            for c in alive:
                m_r = max(1, m_r_base // (r + 1))  # 라운드별 샘플 수 감소
                for _ in range(min(m_r, 5)):  # 추가 제한
                    y = cheap_eval(c['x'])
                    c['samples'].append(y)
                    c['sum'] += y
                c['m'] += min(m_r, 5)
                if c['m'] > 0:
                    c['mean'] = c['sum'] / c['m']
                else:
                    c['mean'] = 0
                
                # Hoeffding 경계 계산
                if c['m'] > 0:
                    ε_q = (b - a) * np.sqrt(np.log(2 / δ_per_comparison) / (2 * c['m']))
                    c['LCB'] = c['mean'] - ε_q
                    c['UCB'] = c['mean'] + ε_q
                else:
                    c['LCB'] = 0
                    c['UCB'] = 0
                
                # 공정성 패널티 (간단한 예시: Jain's index)
                fairness_penalty = 1 - jains_index(c['x'])
                c['penalized_LCB'] = c['LCB'] - λ * fairness_penalty
            
            # 제거 테스트
            if alive:
                best_LCB = max([c['penalized_LCB'] for c in alive])
                for c in alive:
                    if c['UCB'] < best_LCB - margin_margin:
                        c['status'] = 'eliminated'
            
            # 감사
            for c in alive:
                if np.random.rand() < p_audit:
                    full_eval(c['x'])  # 감사용 full 평가
            
            # 생존자 업데이트
            alive = [c for c in candidates if c['status'] == 'alive']
        
        # 최종 생존자 full 평가
        survivors = alive if alive else candidates[:min(3, len(candidates))]  # 수 조정
        for c in survivors:
            c['full_fitness'] = full_eval(c['x'])
            # 전체 효용과 공정성 계산
            utility = c['full_fitness']
            fairness = jains_index(c['x'])
            # 라그랑지안 목적 함수
            c['lagrangian_fitness'] = utility - λ * (1 - fairness)
        
        # 인구 업데이트
        for i in range(N):
            if survivors:
                best_child = max(survivors, key=lambda x: x['lagrangian_fitness'])
                if best_child['lagrangian_fitness'] > full_fitness[i]:
                    P[i] = best_child['x']
                    full_fitness[i] = best_child['full_fitness']
        
        # 서로게이트 모델 업데이트 (샘플 수 제한)
        added_count = 0
        for c in candidates:
            if 'full_fitness' in c and added_count < 5:  # 제한 추가
                X_train = np.vstack([X_train, c['x']])
                y_train = np.append(y_train, c['full_fitness'])
                added_count += 1
        if len(y_train) > N and len(y_train) <= 2*N:  # 조건 수정
            surrogate_model.fit(X_train, y_train)
        
        # 라그랑지 승수 업데이트
        avg_fairness = np.mean([jains_index(x) for x in P])
        λ = max(0, λ + η_λ * (avg_fairness - 0.8))  # 목표 공정성 0.8
        
        # DE 파라미터 감쇠
        F = F_0 * np.exp(-α * gen / T)
        CR = CR_min + (CR_0 - CR_min) * np.exp(-β * gen / T)
        
        # 결과 기록
        best_idx = np.argmax(full_fitness)
        generation_result = {
            "generation": gen,
            "best_fitness": float(full_fitness[best_idx]),
            "best_individual": P[best_idx].tolist(),
            "avg_fitness": float(np.mean(full_fitness)),
            "avg_fairness": float(avg_fairness),
            "lambda": float(λ),
            "time_elapsed": time.time() - start_time
        }
        results["generations"].append(generation_result)
        
        if full_fitness[best_idx] > results["best_fitness"]:
            results["best_fitness"] = float(full_fitness[best_idx])
            results["best_solution"] = P[best_idx].tolist()
    
    return results

# 평가 함수들
def cheap_eval(x):
    # 간단한 noisy 평가 함수 (실제는 시뮬레이션 모델)
    true_value = np.sum(x)  # 예시: 총 효용
    noise = np.random.normal(0, 0.5)
    return max(0, true_value + noise)

def full_eval(x):
    # 고비용 평가 (더 정확한 시뮬레이션)
    true_value = np.sum(x)
    noise = np.random.normal(0, 0.1)
    return max(0, true_value + noise)

def jains_index(x):
    # Jain's fairness index
    if np.sum(x) == 0:
        return 0
    return (np.sum(x)**2) / (len(x) * np.sum(x**2))

# 실험 실행
if __name__ == "__main__":
    results = EAR_DE()
    
    # 결과 저장
    output_dir = "outputs"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    with open(os.path.join(output_dir, "ear_de_results.json"), "w") as f:
        json.dump(results, f, indent=2)
    
    print("Results saved to outputs/ear_de_results.json")