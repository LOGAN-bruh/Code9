"""Model wrapper utilities for safe generation and resilient model loading."""

import inspect
from typing import Any, Callable, Dict, Iterable, Optional, Tuple


class ModelWrapper:
    """Wraps load/generate functions with conservative defaults and fallbacks."""

    def __init__(self, load_fn: Optional[Callable] = None, generate_fn: Optional[Callable] = None):
        self.load_fn = load_fn
        self.generate_fn = generate_fn

    def load(self, *args, **kwargs) -> Any:
        if not self.load_fn:
            return None, None
        return self.load_fn(*args, **kwargs)

    def load_first_available(
        self,
        model_names: Iterable[str],
        base_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Any], Optional[Any], Optional[str], Dict[str, str]]:
        """Try multiple model names and return first successful (model, tokenizer, name, errors)."""
        if not self.load_fn:
            return None, None, None, {"load_fn": "No loader configured."}

        errors: Dict[str, str] = {}
        kwargs = dict(base_kwargs or {})

        for name in model_names:
            try:
                model, tokenizer = self.load_fn(name, **kwargs)
                if model is not None and tokenizer is not None:
                    return model, tokenizer, name, errors
                errors[name] = "Loader returned empty model/tokenizer."
            except Exception as e:
                errors[name] = str(e)

        return None, None, None, errors

    def generate(self, model, tokenizer, prompt: str, max_tokens: int = 200, **kwargs) -> str:
        if not self.generate_fn:
            return ""
        try:
            sig = inspect.signature(self.generate_fn)
            params = sig.parameters
            accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

            call_kwargs = {"prompt": prompt, "max_tokens": max_tokens}

            defaults = {
                "temperature": 0.0,
                "top_p": 0.8,
                "repetition_penalty": 1.25,
            }
            for k, v in defaults.items():
                if k in params or accepts_kwargs:
                    call_kwargs[k] = kwargs.get(k, v)

            for k, v in kwargs.items():
                if k in call_kwargs:
                    continue
                if k in params or accepts_kwargs:
                    call_kwargs[k] = v

            return self.generate_fn(model, tokenizer, **call_kwargs)
        except Exception:
            return self.generate_fn(model, tokenizer, prompt=prompt, max_tokens=max_tokens)
