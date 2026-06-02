import yaml
import os

_config: dict = {}


def _load_config():
    global _config
    if _config:
        return
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)


def get_model(role: str) -> str:
    _load_config()
    env_key = f"MODEL_{role.upper()}"
    fallback = _config["models"].get("orchestrator", "")
    return os.environ.get(env_key, _config["models"].get(role, fallback))


def get_ntfy_config() -> dict:
    _load_config()
    cfg = _config.get("ntfy", {})
    return {
        "server_url": os.environ.get("NTFY_SERVER_URL", cfg.get("server_url", "http://localhost:8080")),
        "topic": os.environ.get("NTFY_TOPIC", cfg.get("topic", "research-agent")),
        "timeout_seconds": int(os.environ.get("NTFY_TIMEOUT", cfg.get("timeout_seconds", 300))),
        "default_on_timeout": cfg.get("default_on_timeout", "approve"),
        # 자체 호스팅 ntfy 인증 (NTFY_USER / NTFY_PASS 환경변수로 설정)
        "username": os.environ.get("NTFY_USER", ""),
        "password": os.environ.get("NTFY_PASS", ""),
    }


def get_verifier_config() -> dict:
    _load_config()
    cfg = _config.get("verifier", {})
    return {
        "max_rounds": int(os.environ.get("VERIFIER_MAX_ROUNDS", cfg.get("max_rounds", 3))),
    }


def get_peer_review_models() -> list[dict]:
    """피어리뷰어 설정 목록을 반환한다. 각 항목: {model, perspective, perspective_kr}"""
    _load_config()
    from shared.prompts import PEER_REVIEW_PERSPECTIVES
    reviewers = _config.get("peer_review", {}).get("reviewers", [])
    result = []
    for r in reviewers:
        perspective = r.get("perspective", "")
        prompt_cfg = PEER_REVIEW_PERSPECTIVES.get(perspective, {})
        result.append({
            "model": r.get("model", get_model("sub_agents")),
            "perspective": perspective,
            "perspective_kr": r.get("perspective_kr", perspective),
            "reviewer_name": prompt_cfg.get("name", perspective),
            "system_prompt": prompt_cfg.get("prompt", ""),
        })
    return result
