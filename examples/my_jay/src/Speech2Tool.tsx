import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Layout } from 'antd';
import { RealtimeClient, RealtimeUtils, EventNames } from '@coze/realtime-api';
import { type OAuthToken, type SimpleBot } from '@coze/api';
import useCozeAPI, {
  BASE_URL,
  INVALID_ACCESS_TOKEN,
  type VoiceOption,
} from './my-coze-api';
import phoneIcon from './assets/phone.svg';
import microphoneIcon from './assets/microphone.svg';
import microphoneOffIcon from './assets/microphone-off.svg';
import cozeLogo from './assets/jay.png';
import closeIcon from './assets/close.svg';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import './MyCozeCallUi.css';
import {MY_COZE_TOKEN, MY_VOICE_ID} from './your_own_config'

const { Sider, Content } = Layout;

const SECONDS_IN_MINUTE = 60;
const PAD_LENGTH = 2;
const TIMER_INTERVAL = 1000;
const CONNECTOR_ID = '1024';

interface CodeProps {
  inline?: boolean;
  className?: string;
  children?: React.ReactNode;
}

const Speech2Tool: React.FC = () => {
  const [isCallActive, setIsCallActive] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [timer, setTimer] = useState(0);
  const [timerInterval, setTimerInterval] = useState<number | null>(null);
  const [bot, setBot] = useState<SimpleBot | null>(null);
  const [voice, setVoice] = useState<VoiceOption | null>(null);
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [accessToken, setAccessToken] = useState<string>(
    MY_COZE_TOKEN,
  );
  const refreshTokenData = MY_COZE_TOKEN;
  const realtimeAPIRef = useRef<RealtimeClient | null>(null);
  const chatContainerRef = useRef<HTMLDivElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  interface EventData {
    time: string;
    type?: string;
    event: string;
    data?: any;
  }

  const [events, setEvents] = useState<EventData[]>([]);
  const [chatMessages, setChatMessages] = useState<EventData[]>([]);
  const [currentMusic, setCurrentMusic] = useState<string | null>(null);
  const [isMusicPlaying, setIsMusicPlaying] = useState<boolean>(false);

  const {
    api,
    getToken,
    refreshToken,
    getVoice,
    getOrCreateRealtimeBot,
    initializeCozeAPI,
  } = useCozeAPI({
    accessToken,
  });

  const tryRefreshToken = useCallback(
    async (errorMsg: string) => {
      if (!`${errorMsg}`.includes(INVALID_ACCESS_TOKEN)) {
        return;
      }

      if (!refreshTokenData) {
        localStorage.removeItem('accessToken');
        return;
      }
    },
    [refreshToken, refreshTokenData],
  );

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / SECONDS_IN_MINUTE);
    const secs = seconds % SECONDS_IN_MINUTE;
    return `${mins.toString().padStart(PAD_LENGTH, '0')}:${secs
      .toString()
      .padStart(PAD_LENGTH, '0')}`;
  };

  const checkMicrophonePermission = async () => {
    try {
      const permission = await RealtimeUtils.checkPermission();
      if (permission) {
        setErrorMessage('');
        console.log('✅ Microphone permission granted');
        return true;
      } else {
        setErrorMessage('Please allow microphone access to start the call');
        return false;
      }
    } catch (error) {
      console.error('❌ Failed to get microphone permission:', error);
      setErrorMessage('Please allow microphone access to start the call');
      return false;
    }
  };

  // 端插件能力，本地调用

  const change_volume = (volume_ctr: string): string => {
    if (audioRef.current) {
      const step = 0.8; // 每次调整的音量步长，这里是为了效果明显
      let newVolume = audioRef.current.volume;
  
      if (volume_ctr === 'volume_up') {
        newVolume = Math.min(1, newVolume + step); // 确保音量不超过 1
      } else if (volume_ctr === 'volume_down') {
        newVolume = Math.max(0.1, newVolume - step); // 确保音量不低于 0.1
      }
  
      audioRef.current.volume = newVolume;
      console.log(`Current volume: ${audioRef.current.volume}`);
    }
    return '音量调节完毕';
  };

  const play_music = (musicName: string): string => {
    if (audioRef.current) {

        if (musicName === 'music_stop') {
            stopMusic();
            return 'Music stopped';
          }
      
        // Check if the musicName is a URL
        const isUrl = musicName.startsWith('https://');
        audioRef.current.src = isUrl ? musicName : `/assets/${musicName}.mp3`;
      audioRef.current.play().catch(error => {
        console.error('Error playing audio:', error);
      });
      setCurrentMusic(musicName);
      setIsMusicPlaying(true);
      return `Playing music: ${musicName}`;
    }
    return 'Audio element not initialized';
  };

  const pauseMusic = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      setIsMusicPlaying(false);
    }
  };

  const resumeMusic = () => {
    if (audioRef.current) {
      audioRef.current.play().catch(error => {
        console.error('Error resuming audio:', error);
      });
      setIsMusicPlaying(true);
    }
  };

  const stopMusic = () => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
      setCurrentMusic(null);
      setIsMusicPlaying(false);
    }
  };

  const search_content = (query: string): string => {
    const encodedQuery = encodeURIComponent(query);
    const searchUrl = `https://www.bing.com/search?q=${encodedQuery}`;
    window.open(searchUrl, '_blank');
    return `Searching for: ${query}`;
  };

  const checkConversationStatus = async (conversationId: string, chatId: string) => {
    const url = `https://api.coze.cn/v3/chat/message/list?conversation_id=${conversationId}&chat_id=${chatId}`;

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        }
      });

      if (!response.ok) {
        throw new Error(`Failed to fetch conversation status: ${response.statusText}`);
      }

      const responseData = await response.json();
      console.log('Conversation status:', responseData);

      if (responseData.code === 0) {
        console.log('Messages:', responseData.data);
      } else {
        console.error('Error fetching messages:', responseData.msg);
      }
    } catch (error) {
      console.error('Error fetching conversation status:', error);
    }
  };

  const submitToolOutputs = async (conversationId: string, chatId: string, toolCallId: string, output: string) => {
    const url = 'https://api.coze.cn/v3/chat/submit_tool_outputs';
    const body = {
      conversation_id: conversationId,
      chat_id: chatId,
      tool_outputs: [
        {
          tool_call_id: toolCallId,
          output: output
        }
      ],
      stream: false
    };

    console.log('-- conversationId :', conversationId)
    console.log('-- toolCallId :', toolCallId)
    console.log('-- chatId :', chatId)
    console.log('-- output :', `{"result":"${output}"}`);

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
      });

      if (!response.ok) {
        throw new Error(`Failed to submit tool outputs: ${response.statusText}`);
      }

      const responseData = await response.json();
      console.log('Response data:', responseData);

      console.log('Tool outputs submitted successfully');
    } catch (error) {
      console.error('Error submitting tool outputs:', error);
    }
  };

  const handleAllMessage = useCallback((eventName: string, data: any) => {
    console.log('event', eventName, data);

    // 处理 扣子Action 要求
    if (eventName === 'server.conversation.chat.requires_action') {
      const { required_action } = data.data;
      console.log('--------required_action------>', required_action)
      if (required_action.type === 'submit_tool_outputs') {
        const toolCall = required_action.submit_tool_outputs.tool_calls[0];
        const functionName = toolCall.function.name;
        const args = JSON.parse(toolCall.function.arguments);

      //音乐播放
      if (functionName === 'play_music') {
          console.log('-- music_name:', args.music_name)
          const result = play_music(args.music_name);

          // 对话状态 检查，调试用
          // checkConversationStatus(String(data.data.conversation_id), String(data.data.id));

          submitToolOutputs(
            String(data.data.conversation_id),
            String(data.data.id),
            String(toolCall.id),
            String(result)
          )
        }
        //打开浏览器
        else if (functionName === 'search_content') {
          console.log('-- search_query:', args.query)
          const result = search_content(args.query);

          // checkConversationStatus(String(data.data.conversation_id), String(data.data.id));

          submitToolOutputs(
            String(data.data.conversation_id),
            String(data.data.id),
            String(toolCall.id),
            String(result)
          )
        }
        // 修改音量
        else if (functionName === 'change_volume') {
            console.log('-- change_volume:', args.volume_ctr)
            const result = change_volume(args.volume_ctr);
  
            // checkConversationStatus(String(data.data.conversation_id), String(data.data.id));
  
            submitToolOutputs(
              String(data.data.conversation_id),
              String(data.data.id),
              String(toolCall.id),
              String(result)
            )
          }
      }
    }

    if (eventName === 'server.conversation.message.completed') {
      const { role, type, content } = data.data;
      if (role === 'assistant' && type === 'function_call') {
        const parsedContent = JSON.parse(content);
        const displayContent = `工具调用：${parsedContent.name}`;
        setChatMessages(prevMessages => [
          ...prevMessages,
          { time: new Date().toISOString(), type, event: eventName, data: { role, content: displayContent } },
        ]);
      } else if (role === 'assistant' && type === 'tool_response') {
        const parsedContent = JSON.parse(content);
        console.log('parsedContent:', parsedContent)
        if (parsedContent.image) {
          setChatMessages(prevMessages => [
            ...prevMessages,
            { time: new Date().toISOString(), type, event: eventName, data: { role, content: `![Image](${parsedContent.image})` } },
          ]);
        } else if (parsedContent.data && parsedContent.data.includes('https://s.coze.cn')) {
          setChatMessages(prevMessages => [
            ...prevMessages,
            { time: new Date().toISOString(), type, event: eventName, data: { role, content: `![Image](${parsedContent.data})` } },
          ]);
        }
        if (parsedContent.data && parsedContent.data.images) {
          parsedContent.data.images.forEach((image: any) => {
            setChatMessages(prevMessages => [
              ...prevMessages,
              { time: new Date().toISOString(), type, event: eventName, data: { role, content: `![Image](${image.image_url})` } },
            ]);
          });
        }
        if (parsedContent.output) {
          setChatMessages(prevMessages => [
            ...prevMessages,
            { time: new Date().toISOString(), type, event: eventName, data: { role, content: `![Image](${parsedContent.output})` } },
          ]);
        }
      } else if (role !== 'assistant' || type !== 'verbose') {
        setChatMessages(prevMessages => [
          ...prevMessages,
          { time: new Date().toISOString(), type, event: eventName, data: { role, content } },
        ]);
      }
    }
  }, []);

  const initializeRealtimeCall = async () => {
    if (!bot?.bot_id) {
      setErrorMessage('Bot not initialized');
      return false;
    }

    try {
      console.log('🚀 Initializing realtime call client:', {
        botId: bot.bot_id,
        voiceId: voice?.value,
      });

      realtimeAPIRef.current = new RealtimeClient({
        accessToken,
        baseURL: BASE_URL,
        botId: bot.bot_id,
        voiceId: MY_VOICE_ID,
        debug: true,
        connectorId: CONNECTOR_ID,
        allowPersonalAccessTokenInBrowser: true,
      });

      setEvents([]);
      setChatMessages([]);

      console.log('📞 Connecting to server...');
      await realtimeAPIRef.current.connect();
      console.log('✅ Server connected successfully');

      realtimeAPIRef.current.on(EventNames.ALL, handleAllMessage);

      return true;
    } catch (error) {
      console.error('❌ Failed to initialize realtime call:', error);
      tryRefreshToken(`${error}`);
      setErrorMessage('Call initialization failed, please try again');
      return false;
    }
  };

  const handleEndCall = () => {
    console.log('👋 Ending call');
    setIsCallActive(false);
    setIsMuted(false);
    if (timerInterval) {
      clearInterval(timerInterval);
      setTimerInterval(null);
    }
    setTimer(0);

    if (realtimeAPIRef.current) {
      console.log('🔌 Disconnecting from server');
      realtimeAPIRef.current.disconnect();
      realtimeAPIRef.current = null;
    }
  };

  const handleToggleMicrophone = () => {
    if (realtimeAPIRef.current) {
      console.log(`🎤 ${isMuted ? 'Unmute' : 'Mute'} microphone`);
      realtimeAPIRef.current.setAudioEnable(isMuted);
      setIsMuted(!isMuted);
    } else {
      console.error('❌ RealtimeClient not initialized');
      setErrorMessage('Call not properly initialized, please try again');
    }
  };

  const handleCall = async () => {
    if (!isCallActive) {
      console.log('🎤 Requesting microphone permission...');
      const hasPermission = await checkMicrophonePermission();
      if (!hasPermission) {
        console.log('❌ Microphone permission denied');
        return;
      }

      console.log('🔄 Initializing call...');
      const initialized = await initializeRealtimeCall();
      if (!initialized) {
        console.log('❌ Call initialization failed');
        return;
      }

      console.log('✅ Call started');
      setIsCallActive(true);
      const interval = setInterval(() => {
        setTimer(prev => prev + 1);
      }, TIMER_INTERVAL);
      setTimerInterval(interval);
    } else {
      console.log('📞 Call ended');
      handleEndCall();
    }
  };

  useEffect(() => {
    const viewport = document.createElement('meta');
    viewport.name = 'viewport';
    viewport.content =
      'width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no';
    document.head.appendChild(viewport);

    return () => {
      document.head.removeChild(viewport);
    };
  }, []);

  useEffect(() => {
    async function init() {
      const newApi = initializeCozeAPI(accessToken);
      if (newApi) {
        console.log('CozeAPI initialized in MyCozeCall');
      } else {
        console.error('Failed to initialize CozeAPI in MyCozeCall');
      }

      try {
        console.log('🤖 Getting or creating Bot...');
        const newBot = await getOrCreateRealtimeBot();
        console.log(
          '✅ Bot retrieved successfully:',
          newBot?.bot_name,
          newBot?.bot_id,
        );
        setBot(newBot);
      } catch (err) {
        console.error('❌ Failed to retrieve Bot:', err);
        tryRefreshToken(`${err}`);
      }

      try {
        console.log('🎵 Getting voice configuration...');
        const newVoice = await getVoice();
        console.log(
          '✅ Voice configuration retrieved successfully:',
          newVoice?.name,
        );
        setVoice(newVoice);
      } catch (err) {
        console.error('❌ Failed to retrieve voice configuration:', err);
        tryRefreshToken(`${err}`);
      }
    }
    init();
  }, [accessToken, api]);

  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [chatMessages]);

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider width={300} style={{ background: '#f0f2f5' }}>
        <div className="phone-container">
          <div className="title-text">我的周杰伦</div>
          <div className="avatar-container">
            <img src={cozeLogo} alt="Bot Avatar" className="avatar-image" />
          </div>
          <div className="status">
            {isCallActive
              ? '智能体对话中'
              : '开始对话'}
          </div>
          {isCallActive && <div className="timer">{formatTime(timer)}</div>}
          {errorMessage && <div className="error-message">{errorMessage}</div>}
          <div className="button-container">
            {isCallActive && (
              <button
                className={`mute-button ${isMuted ? 'muted' : ''}`}
                onClick={handleToggleMicrophone}
              >
                <img
                  src={isMuted ? microphoneOffIcon : microphoneIcon}
                  className={`microphone-icon ${isMuted ? 'muted' : ''}`}
                  alt="microphone"
                />
              </button>
            )}
            <button
              className={`call-button ${isCallActive ? 'active' : ''}`}
              onClick={handleCall}
            >
              {isCallActive ? (
                <img
                  src={closeIcon}
                  className="end-call-icon-svg"
                  alt="end call"
                />
              ) : (
                <img src={phoneIcon} className="call-icon-svg" alt="start call" />
              )}
            </button>
          </div>
        </div>
      </Sider>
      <Content style={{ padding: '20px', background: '#fff' }}>
        <div className="chat-container" ref={chatContainerRef} style={{ maxHeight: '80vh', overflowY: 'auto' }}>
          {chatMessages.map((message, index) => (
            <div
              key={index}
              className={`chat-bubble ${
                message.data.role === 'user' ? 'user-bubble' : 'ai-bubble'
              }`}
              style={{ maxWidth: '70%', margin: '10px auto' }}
            >
              <ReactMarkdown
                className="chat-content"
                children={message.data.content}
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ node, ...props }) => (
                    <a {...props} target="_blank" rel="noopener noreferrer" />
                  ),
                  img: ({ node, ...props }) => (
                    <img {...props} style={{ maxWidth: '100%', height: 'auto' }} alt="image" />
                  ),
                  code({ inline, className, children, ...props }: CodeProps) {
                    return !inline ? (
                      <pre>
                        <code className={className} {...props}>
                          {children}
                        </code>
                      </pre>
                    ) : (
                      <code className={className} {...props}>
                        {children}
                      </code>
                    );
                  },
                }}
              />
            </div>
          ))}
        </div>
        {currentMusic && (
          <div className="music-control">
            <p>Now Playing: {currentMusic}</p>
            {isMusicPlaying ? (
              <button onClick={pauseMusic}>Pause</button>
            ) : (
              <button onClick={resumeMusic}>Play</button>
            )}
            <button onClick={stopMusic}>Stop</button>
          </div>
        )}
        <audio ref={audioRef} />
      </Content>
    </Layout>
  );
};

export default Speech2Tool;