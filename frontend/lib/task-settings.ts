export const STORAGE_KEY_API = "aicreator_api_key";
export const STORAGE_KEY_SILICONFLOW_API_KEY = "aicreator_siliconflow_api_key";
export const STORAGE_KEY_ZHIPU_API_KEY = "aicreator_zhipu_api_key";
export const STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY = "aicreator_siliconflow_image_api_key";
export const STORAGE_KEY_ZHIPU_IMAGE_API_KEY = "aicreator_zhipu_image_api_key";
export const STORAGE_KEY_WECHAT_APPID = "aicreator_wechat_appid";
export const STORAGE_KEY_WECHAT_SECRET = "aicreator_wechat_secret";
export const STORAGE_KEY_AI_PROVIDER = "aicreator_ai_provider";
export const STORAGE_KEY_TEXT_MODEL = "aicreator_text_model";
export const STORAGE_KEY_IMAGE_MODEL = "aicreator_image_model";
export const STORAGE_KEY_SILICONFLOW_TEXT_MODEL = "aicreator_siliconflow_text_model";
export const STORAGE_KEY_SILICONFLOW_IMAGE_MODEL = "aicreator_siliconflow_image_model";
export const STORAGE_KEY_ZHIPU_TEXT_MODEL = "aicreator_zhipu_text_model";
export const STORAGE_KEY_ZHIPU_IMAGE_MODEL = "aicreator_zhipu_image_model";
export const STORAGE_KEY_IMAGE_PROVIDER = "aicreator_image_provider";
export const STORAGE_KEY_RAG_COLLECTION = "aicreator_rag_collection";
export const STORAGE_KEY_RAG_TOP_K = "aicreator_rag_top_k";
export const STORAGE_KEY_RAG_EMBEDDING_MODEL = "aicreator_rag_embedding_model";
export const STORAGE_KEY_RAG_EMBEDDING_PROVIDER = "aicreator_rag_embedding_provider";
export const STORAGE_KEY_RAG_EMBEDDING_API_KEY = "aicreator_rag_embedding_api_key";

export interface RetryCredentials {
  apiKey: string;
  wechatAppid: string;
  wechatAppsecret: string;
  lastShareText: string;
  aiProvider: "siliconflow" | "zhipu";
  textModel: string;
  imageProvider: string;
  imageApiKey: string;
  imageModel: string;
  ragCollection: string;
  ragTopK: number;
  ragEmbeddingModel: string;
  ragEmbeddingProvider: string;
  ragEmbeddingApiKey: string;
}

export function readStoredRetrySettings() {
  if (typeof window === "undefined") {
    return {
      apiKey: "",
      wechatAppid: "",
      wechatAppsecret: "",
      aiProvider: "siliconflow" as const,
      textModel: "",
      imageProvider: "",
      imageApiKey: "",
      imageModel: "",
      ragCollection: "",
      ragTopK: 5,
      ragEmbeddingModel: "",
      ragEmbeddingProvider: "",
      ragEmbeddingApiKey: "",
    };
  }

  const storedProvider = localStorage.getItem(STORAGE_KEY_AI_PROVIDER);
  const validProviders = ["siliconflow", "zhipu"] as const;
  const aiProvider = validProviders.includes(storedProvider as typeof validProviders[number])
    ? (storedProvider as typeof validProviders[number])
    : "siliconflow";

  // 图片服务商：优先读取独立配置，否则跟随主服务商
  const storedImgProvider = localStorage.getItem(STORAGE_KEY_IMAGE_PROVIDER);
  let imageProvider: string;
  if (storedImgProvider === "zhipu" || storedImgProvider === "siliconflow") {
    imageProvider = storedImgProvider;
  } else {
    imageProvider = aiProvider;  // 默认跟随主服务商
  }

  // 图片 API Key：根据图片服务商读取对应 key
  // 优先使用图片服务商专用 API Key，其次才是主 API Key
  const imageApiKey = imageProvider === "zhipu"
    ? localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_API_KEY) || localStorage.getItem(STORAGE_KEY_ZHIPU_API_KEY) || ""
    : localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_API_KEY) || localStorage.getItem(STORAGE_KEY_SILICONFLOW_API_KEY) || "";

  return {
    apiKey: localStorage.getItem(STORAGE_KEY_API) || "",
    wechatAppid: localStorage.getItem(STORAGE_KEY_WECHAT_APPID) || "",
    wechatAppsecret: localStorage.getItem(STORAGE_KEY_WECHAT_SECRET) || "",
    aiProvider,
    textModel: aiProvider === "zhipu"
      ? localStorage.getItem(STORAGE_KEY_ZHIPU_TEXT_MODEL) || localStorage.getItem(STORAGE_KEY_TEXT_MODEL) || ""
      : localStorage.getItem(STORAGE_KEY_SILICONFLOW_TEXT_MODEL) || localStorage.getItem(STORAGE_KEY_TEXT_MODEL) || "",
    imageProvider,
    imageApiKey,
    imageModel: imageProvider === "zhipu"
      ? localStorage.getItem(STORAGE_KEY_ZHIPU_IMAGE_MODEL) || localStorage.getItem(STORAGE_KEY_IMAGE_MODEL) || ""
      : localStorage.getItem(STORAGE_KEY_SILICONFLOW_IMAGE_MODEL) || localStorage.getItem(STORAGE_KEY_IMAGE_MODEL) || "",
    ragCollection: localStorage.getItem(STORAGE_KEY_RAG_COLLECTION) || "",
    ragTopK: parseInt(localStorage.getItem(STORAGE_KEY_RAG_TOP_K) || "5", 10),
    ragEmbeddingModel: localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_MODEL) || "",
    ragEmbeddingProvider: localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_PROVIDER) || "",
    ragEmbeddingApiKey: localStorage.getItem(STORAGE_KEY_RAG_EMBEDDING_API_KEY) || "",
  };
}
