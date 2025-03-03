import base64
import logging
import os
import secrets

from cozepy import (
    COZE_CN_BASE_URL,
    Coze,
    TokenAuth,
    Message,
    MessageObjectString,
    ChatEventType,
    setup_logging,
)
from cozepy.util import write_pcm_to_wav_file

setup_logging(logging.ERROR)


# 主脚本
def run_app(api_base: str, token: str, bot_id: str, audio_path: str, image_path: str):
    coze = Coze(auth=TokenAuth(token), base_url=api_base)

    # 将语音和图片上传到 coze
    audio_file = coze.files.upload(file=audio_path)
    image_file = coze.files.upload(file=image_path)

    # 调用 /v3/chat 发起对话, 传入语音和图片的 file id
    stream = coze.chat.stream(
        bot_id=bot_id,
        user_id=secrets.token_urlsafe(),
        additional_messages=[
            Message.build_user_question_objects(
                [
                    MessageObjectString.build_image(file_id=image_file.id),
                    MessageObjectString.build_audio(file_id=audio_file.id),
                ]
            )
        ],
    )
    print(f"对话开始 logid: {stream.response.logid}")

    # 处理返回的 sse 事件流
    pcm_datas = b""
    for event in stream:
        if event.event == ChatEventType.CONVERSATION_MESSAGE_DELTA:
            # 当事件类型是 conversation.message.delta, 打印到控制台
            print(event.message.content, end="", flush=True)
        elif event.event == ChatEventType.CONVERSATION_AUDIO_DELTA:
            pcm_datas += base64.b64decode(event.message.content)

    wav_audio_path = os.path.join("./output_http_audio.wav")
    write_pcm_to_wav_file(pcm_datas, wav_audio_path)
    print(f"\n保存返回语音到: {wav_audio_path}")


# 主入口
if __name__ == "__main__":
    # 获取输入
    coze_api_base = COZE_CN_BASE_URL
    coze_token = os.getenv("COZE_API_TOKEN") or (
        "请配置你的扣子访问凭据" "please config your coze access_token"
    )
    coze_bot_id = os.getenv("COZE_BOT_ID") or (
        "请配置你的扣子 bot_id" "please config your coze bot_id"
    )
    # 使用本地的文件来使用语音对话+图片识别
    audio_path = "./input_audio.wav"
    image_path = "./input_coze.png"
    # 运行脚本
    run_app(coze_api_base, coze_token, coze_bot_id, audio_path, image_path)
