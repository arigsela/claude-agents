"""Jev (TypeSafe) System One client over plain HTTPS. Spec §5.4, assumption A2 (HTTP, not SDK)."""
from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

JEV_URL = "https://api.typesafe.ai/v1/systemone"
PRICE_PER_MTOK = 0.042
ATTENTION = ("skip", "skim", "read")

QUESTIONS = {
    "attention": {
        "type": "choice",
        "instructions": "How much human review attention does this Kubernetes GitOps pull request need?",
        "criteria": {
            "skip": "Version bump, docs, or comments only; no change to what runs or who can reach it.",
            "skim": "Changes behaviour of a single application in a way a git revert fully undoes "
                    "(config values, resources, probes, replicas).",
            "read": "Changes access control, network exposure, data durability, cluster-wide admission or APIs, "
                    "or something a git revert does not fully undo (deletions, migrations, storage, CRDs).",
        },
    },
    "touches_access_control": {"type": "noul", "instructions":
        "Does this change who or what can access a resource (RBAC, auth, OIDC, service accounts, credentials wiring)?"},
    "changes_network_exposure": {"type": "noul", "instructions":
        "Does this change what traffic can reach a workload or leave it (routes, gateways, network or authorization policies, ports)?"},
    "risks_data_loss": {"type": "noul", "instructions":
        "Could applying this change delete or corrupt stored data (volumes, databases, backups, retention)?"},
    "hard_to_revert": {"type": "noul", "instructions":
        "Would reverting this commit fail to restore the previous state (deletions, migrations, immutable fields, CRD changes)?"},
    "cluster_wide_effect": {"type": "noul", "instructions":
        "Does this change affect workloads beyond the application it names (cluster-scoped resources, shared gateways, admission, node config)?"},
}
FLAGS = tuple(k for k in QUESTIONS if k != "attention")


class JevError(RuntimeError):
    pass


@dataclass
class JevAnswers:
    probabilities: dict[str, float]
    confidence: float
    flags: dict[str, float]
    input_tokens: int

    def to_dict(self) -> dict:
        return {"probabilities": self.probabilities, "confidence": self.confidence, "flags": self.flags}


def parse_response(data: dict) -> JevAnswers:
    try:
        att = data["answers"]["attention"]
        probs = {k: float(att["probabilities"][k]) for k in ATTENTION}
        conf = float(att["confidence"])
        flags = {k: float(data["answers"][k]["noul"]) for k in FLAGS}
        tokens = int((data.get("usage") or {}).get("input_tokens", 0))
    except (KeyError, TypeError, ValueError, AttributeError) as err:
        raise JevError(f"unexpected Jev response shape: {err!r}") from err
    return JevAnswers(probs, conf, flags, tokens)


def ask_jev(state: dict, *, model: str, api_key: str | None = None,
            timeout: float = 5.0, retries: int = 1) -> JevAnswers:
    key = api_key or os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise JevError("TYPESAFE_API_KEY not set")
    payload = json.dumps({"model": model, "state": state, "questions": QUESTIONS}).encode()
    request = urllib.request.Request(JEV_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    last = "no attempt"
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return parse_response(json.load(resp))
        except urllib.error.HTTPError as err:
            last = f"HTTP {err.code}"
            if err.code < 500 and err.code != 429:
                break  # auth/validation errors will not fix themselves
        except (urllib.error.URLError, TimeoutError) as err:
            last = repr(err)
        except JevError:
            raise
        except (ValueError, OSError, http.client.HTTPException) as err:
            last = repr(err)
        if attempt < retries:
            time.sleep(1.0)
    raise JevError(f"Jev request failed: {last}")
