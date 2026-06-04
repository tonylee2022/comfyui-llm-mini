from __future__ import annotations

from comfy_api.latest import IO
from ..core.config import provider_names


class LLMMiniProviderManager(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        providers = provider_names()
        # 允许选择“自定义提供商”来在 ini 里新增
        if "custom_provider" not in providers:
            providers.append("custom_provider")
        return IO.Schema(
            node_id="LLMMiniProviderManager",
            display_name="Provider Manager",
            category="ComfyUI LLM Mini/Config",
            inputs=[
                IO.Combo.Input("provider", options=providers, default=providers[0] if providers else "xai"),
                IO.String.Input(
                    "new_provider_id",
                    optional=True,
                    tooltip="Optional. Start with a letter or number; use only letters, numbers, dots, underscores, or hyphens (maximum 64 characters).",
                ),
            ],
            outputs=[],  # 无任何输出插槽，不连线
            hidden=[
                IO.Hidden.unique_id,
            ],
        )

    @classmethod
    def validate_inputs(cls, **kwargs):
        return True

    @classmethod
    def execute(cls, provider=None, new_provider_id=None, unique_id=None):
        # 仅作为一个占位图形化面板节点，所有逻辑在前端 Web 面板按钮和 server 接口中处理
        return ()
