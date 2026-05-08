export const STORAGE_KEY_API = "aicreator_api_key";
export const STORAGE_KEY_WECHAT_APPID = "aicreator_wechat_appid";
export const STORAGE_KEY_WECHAT_SECRET = "aicreator_wechat_appsecret";
export const STORAGE_KEY_INLINE_IMAGES = "aicreator_generate_inline_images";
export const STORAGE_KEY_AI_PROVIDER = "aicreator_ai_provider";
export const STORAGE_KEY_TEXT_MODEL = "aicreator_text_model";
export const STORAGE_KEY_IMAGE_MODEL = "aicreator_image_model";
export const STORAGE_KEY_RAG_COLLECTION = "aicreator_rag_collection";
export const STORAGE_KEY_RAG_TOP_K = "aicreator_rag_top_k";
export const STORAGE_KEY_RAG_EMBEDDING_MODEL = "aicreator_rag_embedding_model";
export const STORAGE_KEY_RAG_EMBEDDING_PROVIDER = "aicreator_rag_embedding_provider";
export const STORAGE_KEY_RAG_EMBEDDING_API_KEY = "aicreator_rag_embedding_api_key";

export interface RetryCredentials {
  apiKey: string;
  wechatAppid: string;
  wechatAppsecret: string;
  generateInlineImages: boolean;
  lastShareText: string;
  aiProvider: "siliconflow" | "zhipu";
  textModel: string;
  imageModel: string;
}

export function readStoredRetrySettings() {
  if (typeof window === "undefined") {
    return {
      apiKey: "",
      wechatAppid: "",
      wechatAppsecret: "",
      generateInlineImages: false,
      aiProvider: "siliconflow" as const,
      textModel: "",
      imageModel: "",
    };
  }

  const storedProvider = localStorage.getItem(STORAGE_KEY_AI_PROVIDER);
  const validProviders = ["siliconflow", "zhipu"] as const;
  const aiProvider = validProviders.includes(storedProvider as typeof validProviders[number])
    ? (storedProvider as typeof validProviders[number])
    : "siliconflow";

  return {
    apiKey: localStorage.getItem(STORAGE_KEY_API) || "",
    wechatAppid: localStorage.getItem(STORAGE_KEY_WECHAT_APPID) || "",
    wechatAppsecret: localStorage.getItem(STORAGE_KEY_WECHAT_SECRET) || "",
    generateInlineImages:
      localStorage.getItem(STORAGE_KEY_INLINE_IMAGES) === "true",
    aiProvider,
    textModel: localStorage.getItem(STORAGE_KEY_TEXT_MODEL) || "",
    imageModel: localStorage.getItem(STORAGE_KEY_IMAGE_MODEL) || "",
  };
}
