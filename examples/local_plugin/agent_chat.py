import json
import logging
import os
import secrets
import tempfile
import tkinter
from typing import List

from cozepy import (
    COZE_CN_BASE_URL,
    ChatEvent,
    ChatEventType,
    Coze,
    Message,
    Stream,
    TokenAuth,
    ToolOutput,
    setup_logging,
)
from PIL import ImageGrab

setup_logging(logging.ERROR)


class LocalAPI:
    @staticmethod
    def screenshot() -> str:
        """截屏并返回本地临时文件地址"""

        # 获取屏幕尺寸
        win = tkinter.Tk()
        width = win.winfo_screenwidth()
        height = win.winfo_screenheight()
        win.destroy()  # 关闭临时窗口

        # 截取全屏并转换为 RGB 模式
        img = ImageGrab.grab(bbox=(0, 0, width, height)).convert("RGB")

        # 生成临时文件路径 (更低级的方式)
        fd, temp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        img.save(temp_path)

        return temp_path

    @staticmethod
    def list_files(dir: str) -> List[dict]:
        """获取目录下的文件列表, 返回名称和类型"""
        return [{"name": i.name, "type": "file" if i.is_file() else "dir"} for i in os.scandir(dir)]

    @staticmethod
    def read_file(path: str) -> str:
        """读取文件内容"""
        with open(path, "r") as f:
            return f.read()


class LocalPlugin:
    def __init__(self, coze: Coze):
        self.coze = coze

    def screenshot(self, tool_call_id: str, arguments: str) -> ToolOutput:
        temp_path = LocalAPI.screenshot()
        file = self.coze.files.upload(file=temp_path)
        return ToolOutput(
            tool_call_id=tool_call_id,
            output=json.dumps({"image": file.id}),
        )  # 截图端插件定义的出参是 image, 类型是图片

    def list_files(self, tool_call_id: str, arguments: str) -> ToolOutput:
        args = json.loads(arguments)
        dir = args["dir"]  # list_files 端插件定义的入参是 dir
        files = LocalAPI.list_files(dir)

        return ToolOutput(
            tool_call_id=tool_call_id, output=json.dumps({"files": files})
        )  # list_files 端插件定义的出参是 files, 类型是 name + type 的数组

    def read_file(self, tool_call_id: str, arguments: str) -> ToolOutput:
        args = json.loads(arguments)
        path = args["path"]  # read_file 端插件定义的入参是 path
        content = LocalAPI.read_file(path)

        return ToolOutput(
            tool_call_id=tool_call_id,
            output=json.dumps(
                {
                    "content": content,
                }
            ),
        )  # read_file 端插件定义的出参是 content, 类型是 string


# 端插件处理器, 支持处理端插件 example 中的三个插件
def handle_local_plugin(coze: Coze, event: ChatEvent):
    required_action = event.chat.required_action
    tool_call = required_action.submit_tool_outputs.tool_calls[0]
    # 封装了本地的三个插件(LocalAPI -> LocalPlugin): 获取目录、文件、截屏
    local_plugin = LocalPlugin(coze)

    # 通过端插件中断事件中的 tool_call 信息, 并调用对应的插件处理器
    if tool_call.function.name in ["screenshot", "list_files", "read_file"]:
        print(f" > 执行端插件: {tool_call.function.name}, 参数: {tool_call.function.arguments}")
        local_plugin_api = getattr(local_plugin, tool_call.function.name)
        output = local_plugin_api(tool_call.id, tool_call.function.arguments)
        handle_coze_stream(
            coze,
            "/v3/chat/submit_tool_outputs",
            coze.chat.submit_tool_outputs(
                conversation_id=event.chat.conversation_id,
                chat_id=event.chat.id,
                tool_outputs=[output],
                stream=True,
            ),
        )


# SSE 事件处理器
def handle_coze_stream(coze: Coze, api: str, stream: Stream[ChatEvent]):
    # 本次示例处理 3 个事件: 一个是模型输出, 一个是端插件中断, 一个是输出 logid debug.
    is_first_pkg = True
    for event in stream:
        if is_first_pkg:
            print(f"[{api}] logid: {event.response.logid}")

        # 模型输出事件, 直接 print 到控制台即可
        if event.event == ChatEventType.CONVERSATION_MESSAGE_DELTA:
            print(event.message.content, end="", flush=True)

        # 端插件中断, 需要根据端插件的类型分别处理, 比较复杂, 定义一个单独的函数处理
        if event.event == ChatEventType.CONVERSATION_CHAT_REQUIRES_ACTION:
            handle_local_plugin(coze, event)

        is_first_pkg = False


# 运行端插件 example 智能体
def run_local_plugin_app(token: str, api_base: str, bot_id: str, user_id: str, user_input: str):
    # 使用 token 和 base_url 构建一个 coze python 客户端
    coze = Coze(auth=TokenAuth(token), base_url=api_base)
    # 使用 .chat.stream 发起一个 /v3/chat 流式对话
    stream = coze.chat.stream(
        bot_id=bot_id, user_id=user_id, additional_messages=[Message.build_user_question_text(user_input)]
    )
    # 这个 api 会返回一系列 SSE 事件, 定义一个函数来处理这些事件
    handle_coze_stream(coze, "/v3/chat", stream)


# 主入口
if __name__ == "__main__":
    # 获取输入
    coze_api_base = COZE_CN_BASE_URL
    coze_token = os.getenv("COZE_API_TOKEN") or ("请配置你的扣子访问凭据" "please config your coze access_token")
    coze_bot_id = os.getenv("COZE_BOT_ID") or ("请配置你的扣子 bot_id" "please config your coze bot_id")
    your_user_id = secrets.token_urlsafe()

    # 循环获取用户输入, 触发智能体和端插件
    while True:
        # 获取用户的输入, 在控制台输入
        your_user_input = input("\n-----\n请输入你的问题：")

        # 使用 token, bot_id 和输入运行智能体对话
        run_local_plugin_app(coze_token, coze_api_base, coze_bot_id, your_user_id, your_user_input)
