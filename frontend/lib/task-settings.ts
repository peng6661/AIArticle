export const STORAGE_KEY_API = "aicreator_api_key";
export const STORAGE_KEY_WECHAT_APPID = "aicreator_wechat_appid";
export const STORAGE_KEY_WECHAT_SECRET = "aicreator_wechat_appsecret";
export const STORAGE_KEY_INLINE_IMAGES = "aicreator_generate_inline_images";

export interface RetryCredentials {
  apiKey: string;
  wechatAppid: string;
  wechatAppsecret: string;
  generateInlineImages: boolean;
  lastShareText: string;
}

export function readStoredRetrySettings() {
  if (typeof window === "undefined") {
    return {
      apiKey: "",
      wechatAppid: "",
      wechatAppsecret: "",
      generateInlineImages: false,
    };
  }

  return {
    apiKey: localStorage.getItem(STORAGE_KEY_API) || "",
    wechatAppid: localStorage.getItem(STORAGE_KEY_WECHAT_APPID) || "",
    wechatAppsecret: localStorage.getItem(STORAGE_KEY_WECHAT_SECRET) || "",
    generateInlineImages:
      localStorage.getItem(STORAGE_KEY_INLINE_IMAGES) === "true",
  };
}
