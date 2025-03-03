import asyncio
import json
import logging
import os

from cozepy import (
    COZE_CN_BASE_URL,
    TokenAuth,
    AsyncCoze,
    AsyncWebsocketsChatEventHandler,
    AsyncWebsocketsChatClient,
    InputAudioBufferAppendEvent,
    ChatUpdateEvent,
    ConversationChatCreatedEvent,
    ConversationMessageDeltaEvent,
    ConversationAudioDeltaEvent,
    ConversationChatCompletedEvent,
)
from cozepy.log import log_info, setup_logging
from cozepy.util import write_pcm_to_wav_file

setup_logging(logging.ERROR)


class WebsocketsChatEventHandler(AsyncWebsocketsChatEventHandler):
    delta = []

    async def on_error(self, cli: AsyncWebsocketsChatClient, e: Exception):
        import traceback

        log_info(f"Error occurred: {str(e)}")
        log_info(f"Stack trace:\n{traceback.format_exc()}")

    async def on_conversation_chat_created(
        self, cli: AsyncWebsocketsChatClient, event: ConversationChatCreatedEvent
    ):
        print(f"对话开始 logid: {event.detail.logid}")

    async def on_conversation_message_delta(
        self, cli: AsyncWebsocketsChatClient, event: ConversationMessageDeltaEvent
    ):
        print(event.data.content, end="", flush=True)

    async def on_conversation_audio_delta(
        self, cli: AsyncWebsocketsChatClient, event: ConversationAudioDeltaEvent
    ):
        self.delta.append(event.data.get_audio())

    async def on_conversation_chat_completed(
        self, cli: "AsyncWebsocketsChatClient", event: ConversationChatCompletedEvent
    ):
        wav_audio_path = os.path.join("./output_ws_audio.wav")
        write_pcm_to_wav_file(b"".join(self.delta), wav_audio_path)
        print(f"\n保存返回语音到: {wav_audio_path}")


def split_bytes_by_length(data, length):
    res = []
    for i in range(0, len(data), length):
        res.append(data[i : i + length])
    return res


# 主脚本
async def run_app(
    api_base: str,
    token: str,
    bot_id: str,
    workflow_id: str,
    audio_path: str,
    image_path: str,
):
    coze = AsyncCoze(auth=TokenAuth(token), base_url=api_base)

    # 将图片上传到 coze
    image_file = await coze.files.upload(file=image_path)
    print(f"图片上传结果 {image_file.id}")
    # 低于语音数据
    with open(audio_path, "rb") as f:
        audio_data = f.read()

    chat = coze.websockets.chat.create(
        bot_id=bot_id,
        workflow_id=workflow_id,
        on_event=WebsocketsChatEventHandler(),
    )

    # 建立 websocket 链接
    async with chat() as client:
        print("建立 websocket 链接成功")
        # 发送 chat_flow 参数
        await client.chat_update(
            ChatUpdateEvent.Data.model_validate(
                {
                    "chat_config": ChatUpdateEvent.ChatConfig.model_validate(
                        {
                            "parameters": {
                                "image": json.dumps(
                                    {
                                        "file_id": image_file.id,
                                    }
                                ),
                            }
                        }
                    )
                }
            )
        )
        # 发送语音数据
        for delta in split_bytes_by_length(audio_data, 1024):
            await client.input_audio_buffer_append(
                InputAudioBufferAppendEvent.Data.model_validate(
                    {
                        "delta": delta,
                    }
                )
            )
            await asyncio.sleep(len(delta) * 1.0 / 24000 / 2)  # 模拟真实说话间隔
        await client.input_audio_buffer_complete()
        await client.wait()


# main 入口异步函数
async def main():
    # 获取输入
    coze_api_base = COZE_CN_BASE_URL
    coze_token = os.getenv("COZE_API_TOKEN") or (
        "请配置你的扣子访问凭据" "please config your coze access_token"
    )
    coze_bot_id = os.getenv("COZE_BOT_ID") or (
        "请配置你的扣子 bot_id" "please config your coze bot_id"
    )
    coze_workflow_id = os.getenv("COZE_WORKFLOW_ID") or (
        "请配置你的扣子 workflow_id" "please config your coze workflow_id"
    )
    # 使用本地的文件来使用语音对话+图片识别
    audio_path = "./input_audio.wav"
    image_path = "./input_coze.png"
    # 运行脚本
    await run_app(
        coze_api_base, coze_token, coze_bot_id, coze_workflow_id, audio_path, image_path
    )


# 主入口
if __name__ == "__main__":
    asyncio.run(main())
