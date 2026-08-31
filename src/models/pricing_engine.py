"""
基于XGBoost的球星卡定价引擎
==========================
训练时对价格取对数(log-transform)，支持SHAP归因分析，
输出每个因素对价格的边际贡献（转换回价格空间）。

用法:
    engine = PricingEngine()
    engine.fit(X_train, y_train)
    result = engine.predict(X_test)  # {price, ci_low, ci_high, attribution}
"""

import numpy as np
import joblib
import os
import warnings

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_percentage_error


class PricingEngine:
    """
    XGBoost定价引擎

    在log(price)空间训练，预测时exp还原到原始价格空间。
    使用SHAP TreeExplainer进行特征归因分析。
    """

    def __init__(self, params=None):
        """
        初始化定价引擎

        Args:
            params: XGBoost参数字典，None则使用默认参数
        """
        self.params = params or {
            "n_estimators": 300,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
            "reg_alpha": 0.1,
            "reg_lambda": 1.0,
            "min_child_weight": 3,
            "random_state": 42,
            "verbosity": 0,
            "objective": "reg:squarederror",
        }
        self.model = None
        self.shap_explainer = None
        self.is_fitted = False
        self._train_std = None       # 训练集残差标准差（用于置信区间）
        self._residual_quantiles = None  # 残差分位数

    def fit(self, X, y, sample_weight=None, val_size=0.2, random_seed=42):
        """
        训练定价模型

        Args:
            X: np.ndarray, 特征矩阵
            y: np.ndarray, 原始价格（非对数）
            sample_weight: 样本权重（可选，真实数据可给更高权重）
            val_size: 验证集比例
            random_seed: 随机种子

        Returns:
            self
        """
        # ---- 对数变换 ----
        y_log = np.log(np.maximum(y, 0.1))
        y_log_mean = np.mean(y_log)
        y_log_std = np.std(y_log)

        print(f"[定价引擎] 训练集大小: {len(X)}, log(price)均值={y_log_mean:.3f}, 标准差={y_log_std:.3f}")

        # ---- 拆分训练/验证集 ----
        X_train, X_val, y_train_log, y_val_log = train_test_split(
            X, y_log, test_size=val_size, random_state=random_seed
        )

        # ---- 训练 XGBoost ----
        self.model = xgb.XGBRegressor(**self.params)

        # 拆分样本权重
        w_train = None
        if sample_weight is not None:
            w_train, w_val = train_test_split(
                sample_weight, test_size=val_size, random_state=random_seed
            )

        self.model.fit(
            X_train, y_train_log,
            sample_weight=w_train,
            eval_set=[(X_val, y_val_log)],
            verbose=False,
        )

        # ---- 评估 ----
        y_val_pred_log = self.model.predict(X_val)
        y_val_true = np.exp(y_val_log)
        y_val_pred = np.exp(y_val_pred_log)
        mape = mean_absolute_percentage_error(y_val_true, y_val_pred)
        print(f"[定价引擎] 验证集 MAPE: {mape:.2%}")

        # ---- 计算训练集残差 ----
        y_train_pred_log = self.model.predict(X_train)
        residuals = y_train_log - y_train_pred_log
        self._train_std = np.std(residuals)
        self._residual_quantiles = np.percentile(residuals, [2.5, 97.5])

        # ---- 拟合 SHAP 解释器（使用训练集子集提高速度）----
        try:
            import shap
            n_shap = min(500, len(X_train))
            # XGBoost 3.x 兼容：使用 shap.TreeExplainer 而非 xgboost.tree
            self.shap_explainer = shap.TreeExplainer(self.model)
            # 预热SHAP
            _ = self.shap_explainer.shap_values(X_train[:n_shap])
            print("[定价引擎] SHAP解释器已就绪")
        except Exception as e:
            print(f"[定价引擎] SHAP初始化警告: {e}，将使用特征重要性替代")
            self.shap_explainer = None

        self.is_fitted = True
        return self

    def predict(self, X, return_attribution=True):
        """
        预测卡片价格

        Args:
            X: np.ndarray, shape (n_samples, n_features)
            return_attribution: 是否返回SHAP归因

        Returns:
            result: dict 或 list of dict
                - price: 预估价格 (¥)
                - price_log: log空间预测值
                - ci_low: 置信区间下界 (¥)
                - ci_high: 置信区间上界 (¥)
                - attribution: {feature_name: contribution_rmb} (仅return_attribution=True)
        """
        if not self.is_fitted:
            raise RuntimeError("模型尚未训练，请先调用 fit()")

        is_single = (X.ndim == 1) or (X.shape[0] == 1)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        # ---- 预测 ----
        y_pred_log = self.model.predict(X)

        # ---- 置信区间 ----
        log_ci_low = y_pred_log + self._residual_quantiles[0]
        log_ci_high = y_pred_log + self._residual_quantiles[1]
        # 也可以用 1.96 * train_std
        log_ci_low_alt = y_pred_log - 1.96 * self._train_std
        log_ci_high_alt = y_pred_log + 1.96 * self._train_std

        prices = np.exp(y_pred_log)
        ci_low = np.exp(log_ci_low)
        ci_high = np.exp(log_ci_high)

        # ---- SHAP 归因 ----
        attributions = None
        if return_attribution and self.shap_explainer is not None:
            try:
                from src.features.card_encoder import FEATURE_NAMES, get_feature_display_names

                shap_values = self.shap_explainer.shap_values(X)
                # shap_values 在 log 空间，需转换到价格空间
                # 方法：每个特征的SHAP值贡献到log_price，转为原始价格贡献
                # price = exp(base + sum(shap_i))
                # 每个特征的价格贡献 ≈ exp(base) * (exp(shap_i) - 1) 的一阶近似
                # 更直观的：用 SHAP值 × 预测价格 / log预测价格 的近似

                base_log = self.shap_explainer.expected_value
                if isinstance(base_log, np.ndarray):
                    base_log = base_log[0]

                display_names = get_feature_display_names()

                attributions = []
                for i in range(len(X)):
                    # 将log空间的SHAP值转换为价格空间的贡献
                    shap_log = shap_values[i]
                    pred_price = prices[i]
                    pred_log = y_pred_log[i]

                    # 转换：每个特征的log贡献 -> 价格贡献
                    # price = exp(base + Σshap) = exp(base) * Πexp(shap)
                    # 第j个特征的价格贡献 = price * (exp(shap_j) - 1) / Σ(exp(shap_j) - 1)  近似
                    # 更简单且直观的方法：用比例分配
                    total_shap_abs = np.sum(np.abs(shap_log))
                    if total_shap_abs > 0:
                        attr_dict = {}
                        for j, fname in enumerate(FEATURE_NAMES):
                            if len(FEATURE_NAMES) > len(shap_log):
                                break
                            # SHAP值在log空间，贡献比例 ≈ shap_j / Σ|shap|
                            # 价格贡献 = 比例 × 预测价格（近似）
                            contribution = (shap_log[j] / total_shap_abs) * pred_price
                            display_name = display_names.get(fname, fname)
                            attr_dict[display_name] = round(float(contribution), 2)
                    else:
                        attr_dict = {display_names.get(f, f): 0.0 for f in FEATURE_NAMES}

                    attributions.append(attr_dict)

            except Exception as e:
                print(f"[定价引擎] SHAP归因计算警告: {e}")
                attributions = None

        # ---- 组装结果 ----
        results = []
        for i in range(len(X)):
            r = {
                "price": round(float(prices[i]), 2),
                "price_log": round(float(y_pred_log[i]), 4),
                "ci_low": round(float(ci_low[i]), 2),
                "ci_high": round(float(ci_high[i]), 2),
            }
            if attributions is not None:
                r["attribution"] = attributions[i]
            results.append(r)

        return results[0] if is_single else results

    def evaluate(self, X_test, y_test):
        """
        在测试集上评估模型性能

        Args:
            X_test: 测试集特征
            y_test: 测试集真实价格

        Returns:
            metrics: dict, {mape, rmse_log, r2}
        """
        y_pred_log = self.model.predict(X_test)
        y_pred = np.exp(y_pred_log)

        mape = mean_absolute_percentage_error(y_test, y_pred)
        rmse_log = np.sqrt(np.mean((np.log(np.maximum(y_test, 0.1)) - y_pred_log) ** 2))

        # R² on log space
        y_log_true = np.log(np.maximum(y_test, 0.1))
        ss_res = np.sum((y_log_true - y_pred_log) ** 2)
        ss_tot = np.sum((y_log_true - np.mean(y_log_true)) ** 2)
        r2_log = 1 - ss_res / ss_tot if ss_tot > 0 else 0

        metrics = {
            "mape": round(float(mape), 4),
            "rmse_log": round(float(rmse_log), 4),
            "r2_log": round(float(r2_log), 4),
        }
        return metrics

    def get_feature_importance(self):
        """
        获取特征重要性（基于XGBoost内置重要性）

        Returns:
            list of (feature_name, importance)
        """
        if not self.is_fitted:
            raise RuntimeError("模型尚未训练")

        from src.features.card_encoder import FEATURE_NAMES, get_feature_display_names

        importance = self.model.feature_importances_
        display_names = get_feature_display_names()

        result = []
        for j, imp in enumerate(importance):
            if j < len(FEATURE_NAMES):
                name = display_names.get(FEATURE_NAMES[j], FEATURE_NAMES[j])
                result.append((name, round(float(imp), 6)))
        result.sort(key=lambda x: x[1], reverse=True)
        return result

    def save(self, filepath):
        """保存模型"""
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else ".", exist_ok=True)
        # XGBoost 3.x: 使用临时文件保存模型字节
        import tempfile
        tmp_path = None
        model_bytes = None
        if self.model:
            tmp_path = tempfile.mktemp(suffix='.json')
            self.model.save_model(tmp_path)
            with open(tmp_path, 'rb') as f:
                model_bytes = f.read()
            os.unlink(tmp_path)

        data = {
            "model_bytes": model_bytes,
            "params": self.params,
            "is_fitted": self.is_fitted,
            "train_std": self._train_std,
            "residual_quantiles": self._residual_quantiles,
        }
        joblib.dump(data, filepath)
        print(f"[定价引擎] 已保存到 {filepath}")

    @classmethod
    def load(cls, filepath):
        """加载模型"""
        data = joblib.load(filepath)
        engine = cls(params=data["params"])
        engine.is_fitted = data["is_fitted"]
        engine._train_std = data["train_std"]
        engine._residual_quantiles = data["residual_quantiles"]

        if data["model_bytes"]:
            import tempfile
            tmp_path = tempfile.mktemp(suffix='.json')
            with open(tmp_path, 'wb') as f:
                f.write(data["model_bytes"])
            engine.model = xgb.XGBRegressor()
            engine.model.load_model(tmp_path)
            os.unlink(tmp_path)

            # 重新拟合SHAP解释器
            try:
                import shap
                engine.shap_explainer = shap.TreeExplainer(engine.model)
                print(f"[定价引擎] 已从 {filepath} 加载模型和SHAP解释器")
            except Exception as e:
                print(f"[定价引擎] SHAP加载警告: {e}")
                engine.shap_explainer = None
        else:
            print(f"[定价引擎] 已从 {filepath} 加载（无模型数据）")

        return engine
