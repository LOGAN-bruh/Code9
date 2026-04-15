"""Model wrapper utilities for safe generation and parameter handling.

This module provides a lightweight ModelWrapper class that adapts to different
`load`/`generate` call signatures and supplies conservative decoding defaults.
"""
import inspect
from typing import Any, Callable, Optional


class ModelWrapper:
    """Wraps model load/generate functions and offers safe-generate helper.

    Usage:
      mw = ModelWrapper(load_fn=load, generate_fn=generate)
      model, tokenizer = mw.load("model-name", device="cpu")
      text = mw.generate(model, tokenizer, prompt, max_tokens=300)
    """

    def __init__(self, load_fn: Optional[Callable] = None, generate_fn: Optional[Callable] = None):
        self.load_fn = load_fn
        self.generate_fn = generate_fn

    def load(self, *args, **kwargs) -> Any:
        """Call the provided load function (if any) and return (model, tokenizer).
        Falls back to returning (None, None) if no loader is provided.
        """
        if not self.load_fn:
            return None, None
        return self.load_fn(*args, **kwargs)

    def generate(self, model, tokenizer, prompt: str, max_tokens: int = 200, **kwargs) -> str:
        """Call the generate function using conservative decoding defaults when supported.

        The wrapper inspects the generate() signature and only passes parameters the
        underlying function accepts. Common safe defaults: temperature=0.2, top_p=0.9,
        repetition_penalty=1.2.
        """
        if not self.generate_fn:
            return ""
        try:
            sig = inspect.signature(self.generate_fn)
            params = sig.parameters
            call_kwargs = {"prompt": prompt, "max_tokens": max_tokens}
            # Only set conservative params if underlying implementation accepts them
            if "temperature" in params:
                call_kwargs["temperature"] = kwargs.get("temperature", 0.2)
            if "top_p" in params:
                call_kwargs["top_p"] = kwargs.get("top_p", 0.9)
            if "repetition_penalty" in params:
                call_kwargs["repetition_penalty"] = kwargs.get("repetition_penalty", 1.2)
            # Merge any explicit kwargs passed by caller
            for k, v in kwargs.items():
                if k not in call_kwargs and k in params:
                    call_kwargs[k] = v
            return self.generate_fn(model, tokenizer, **call_kwargs)
        except Exception:
            # Last-resort: try the simple call
            return self.generate_fn(model, tokenizer, prompt=prompt, max_tokens=max_tokens)
