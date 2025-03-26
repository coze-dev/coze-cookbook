import { useEffect, useState } from 'react';
import {MY_COZE_TOKEN,MY_BOT_NAME} from './your_own_config'

import {
  CozeAPI,
  type WorkSpace,
  type SimpleBot,
} from '@coze/api';

export interface VoiceOption {
  label: React.ReactNode;
  value: string;
  preview_url?: string;
  name: string;
  language_code: string;
  language_name: string;
  is_system_voice: boolean;
  available_training_times: number;
  preview_text: string;
}

export interface BotOption {
  value: string;
  label: string;
  avatar?: string;
}

export interface WorkspaceOption {
  value: string;
  label: string;
}


export const BASE_URL = 'https://api.coze.cn';

export const INVALID_ACCESS_TOKEN = 'code: 4100';

const useCozeAPI = ({ accessToken }: { accessToken: string }) => {
  const [api, setApi] = useState<CozeAPI | null>(null);
  const [isLoading, setIsLoading] = useState(true);


  const initializeCozeAPI = (accessToken: string | null): CozeAPI | null => {
    if (!accessToken) {
      console.log('No accessToken available');
      return null;
    }
  
    console.log('Initializing CozeAPI with accessToken:', accessToken);
    try {
      const newApi = new CozeAPI({
        token: accessToken,
        baseURL: BASE_URL,
        allowPersonalAccessTokenInBrowser: true,
      });
      console.log('CozeAPI initialized successfully');
      return newApi;
    } catch (error) {
      console.error('Failed to initialize CozeAPI:', error);
      return null;
    }
  };

  useEffect(() => {
    if (accessToken) {
      console.log('Initializing CozeAPI with accessToken:', accessToken);
      try {
        const newApi = new CozeAPI({
          token: accessToken,
          baseURL: BASE_URL,
          allowPersonalAccessTokenInBrowser: true,
        });

        setApi(prevApi => {
          if (prevApi !== newApi) {
            console.log('Updating API instance');
            return newApi;
          }
          return prevApi;
        });

        console.log('CozeAPI initialized successfully');
      } catch (error) {
        console.error('Failed to initialize CozeAPI:', error);
      } finally {
        setIsLoading(false);
      }
    } else {
      console.log('No accessToken available');
      setApi(null); // Ensure api is null if no accessToken
      setIsLoading(false);
    }
  }, [accessToken]);



  const getToken = async (
    code: string,
    codeVerifier: string,
  ): Promise<string> =>{
    return MY_COZE_TOKEN;
  };

  const refreshToken = async (refreshTokenStr: string): Promise<string> =>
    {
        return MY_COZE_TOKEN;
    };

  const getPersonalWorkspace = async (): Promise<WorkSpace | null> => {

    if (!api) {
        console.error('API is not initialized');
        return null;
      }
      
    const pageSize = 50;
    let pageNum = 1;
    let hasMore = true;
    while (hasMore) {
      const workspaces = await api?.workspaces.list({
        page_num: pageNum,
        page_size: pageSize,
      });
      console.log(`get workspaces 2: ${workspaces?.workspaces.length}`);
      for (const workspace of workspaces?.workspaces || []) {
        console.log(`get workspace: ${workspace.name} ${workspace.id}`);
        if (workspace.workspace_type === 'personal') {
          return workspace;
        }
      }
      hasMore = workspaces?.workspaces.length === pageSize;
      pageNum++;
    }
    return null;
  };

  const getBotByName = async (
    workspaceId: string,
    botName: string,
  ): Promise<SimpleBot | null> => {
    let pageIndex = 1;
    const pageSize = 20;
    let hasMore = true;

    try {
      while (hasMore) {
        const response = await api?.bots.list({
          space_id: workspaceId,
          page_size: pageSize,
          page_index: pageIndex,
        });

        for (const bot of response?.space_bots || []) {
          if (bot.bot_name === botName) {
            return bot;
          }
        }

        hasMore = response?.space_bots.length === pageSize;
        pageIndex++;
      }

      return null;
    } catch (error) {
      console.error('get getBotByName error:', error);
      throw error;
    }
  };

  const fetchAllVoices = async (): Promise<VoiceOption[]> => {
    try {
      const response = await api?.audio.voices.list();

      // Separate system voices and custom voices
      const customVoices =
        response?.voice_list.filter(voice => !voice.is_system_voice) || [];
      const systemVoices =
        response?.voice_list.filter(voice => voice.is_system_voice) || [];

      // Group system voices by language
      const systemVoicesByLanguage = systemVoices.reduce<
        Record<string, typeof systemVoices>
      >((acc, voice) => {
        const languageName = voice.language_name;
        if (!acc[languageName]) {
          acc[languageName] = [];
        }
        acc[languageName].push(voice);
        return acc;
      }, {});

      // Sort languages alphabetically and flatten voices
      const sortedSystemVoices = Object.entries(systemVoicesByLanguage)
        .sort(([langA], [langB]) => langB.localeCompare(langA))
        .flatMap(([, voices]) => voices);

      // Merge custom voices with sorted system voices and format
      const formattedVoices = [...customVoices, ...sortedSystemVoices].map(
        voice => ({
          value: voice.voice_id,
          preview_url: voice.preview_audio,
          name: voice.name,
          language_code: voice.language_code,
          language_name: voice.language_name,
          is_system_voice: voice.is_system_voice,
          label: `${voice.name} (${voice.language_name})`,
          preview_text: voice.preview_text,
          available_training_times: voice.available_training_times,
        }),
      );

      return formattedVoices;
    } catch (error) {
      console.error('get voices error:', error);
      throw error;
    }
  };

  const getVoice = async (): Promise<VoiceOption | null> => {
    try {
      const voices = await fetchAllVoices();
      console.log('Fetched voices:', voices);
  
      if (voices.length === 0) {
        console.log('No voices available');
        return null;
      }
  
      // 查找自定义语音
      const customVoice = voices.find(voice => !voice.is_system_voice);
      if (customVoice) {
        console.log('Custom voice found:', customVoice);
        let  firstVoice = voices[38];
        return firstVoice;
      }
  
      // 返回第一个语音
      const firstVoice = voices[38];
      console.log('No custom voice found, returning first voice:', firstVoice);
      return firstVoice;
    } catch (error) {
      console.error('Error fetching voices:', error);
      return null;
    }
  };

  const getOrCreateRealtimeBot = async (): Promise<SimpleBot | null> => {
    try {
      // Get personal workspace
      const personalWorkspace = await getPersonalWorkspace();
      if (!personalWorkspace) {
        throw new Error('Personal workspace not found');
      }

      const botName = MY_BOT_NAME;

      // Get all bots
      const realtimeCallUpBot = await getBotByName(
        personalWorkspace.id,
        botName,
      );

      if (realtimeCallUpBot) {
        return realtimeCallUpBot;
      }

      // Create new bot if it doesn't exist
      const newBot = await api?.bots.create({
        space_id: personalWorkspace.id,
        name: botName,
        description: 'A bot for realtime call up demo',
        onboarding_info: {
          prologue: '你好呀，我是你的智能助手，有什么可以帮到你的吗？',
        },
      });

      if (!newBot) {
        throw new Error('Failed to create bot');
      }

      // Publish to API channel
      await api?.bots.publish({
        bot_id: newBot.bot_id,
        connector_ids: ['API'],
      });

      return {
        bot_id: newBot.bot_id,
        bot_name: botName,
        description: '',
        icon_url: '',
        publish_time: '',
      };
    } catch (error) {
      console.error('Failed to get or create bot:', error);
      throw error;
    }
  };

  return {
    api,
    getToken,
    refreshToken,
    getVoice,
    getOrCreateRealtimeBot,
    initializeCozeAPI,
  };
};

export default useCozeAPI;
