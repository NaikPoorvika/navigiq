/** Typed wrappers for every backend route the UI uses. */
import { api } from "@/lib/api/client";
import type {
  AssistantResponse, CategoryInfo, CollectionsResponse, HomeContext, Modification, ModifyResponse,
  PlanListItem, PlanOutcome, PlanVersion, PlanView, PoiDetail, PoiListResponse, Preferences,
  RecommendResponse, SavedItem, TokenPair, TripSpec, User,
} from "@/lib/api/types";

export interface RecommendArgs {
  interests?: string[];
  moods?: string[];
  avoid?: string[];
  area?: string;
  scope?: "local" | "city" | "regional" | "anywhere";
  budget_per_person?: number;
  party_type?: string;
  mode?: "discover" | "hidden_gems" | "for_you" | "surprise" | "different";
  indoor_preference?: "indoor" | "outdoor" | "any";
  rain_expected?: boolean;
  quiet?: boolean;
  kids?: boolean;
  exclude_ids?: number[];
  limit?: number;
}

export interface PoiQuery {
  q?: string;
  category?: string[];
  tag?: string[];
  area?: string;
  scope?: "city" | "regional" | "anywhere";
  max_cost?: number;
  limit?: number;
}

export const endpoints = {
  // context & discovery
  context: () => api.get<HomeContext>("/context"),
  categories: () => api.get<{ categories: CategoryInfo[]; moods: string[] }>("/pois/categories"),
  pois: (q: PoiQuery, signal?: AbortSignal) =>
    api.get<PoiListResponse>("/pois", { ...q } as Record<string, string | number | string[] | undefined>, signal),
  recommend: (args: RecommendArgs) =>
    api.post<RecommendResponse>("/pois/recommend", args as Record<string, unknown>),
  surprise: (args: RecommendArgs = {}) =>
    api.post<RecommendResponse>("/pois/surprise", args as Record<string, unknown>),
  collections: (ids?: string[], limit = 8) =>
    api.get<CollectionsResponse>("/collections", { ids, limit }),
  poi: (id: number | string) => api.get<PoiDetail>(`/pois/${id}`),
  similar: (id: number, limit = 6) =>
    api.get<RecommendResponse & { reference: PoiDetail }>(`/pois/${id}/similar`, { limit }),
  save: (id: number) => api.post<{ poi_id: number; saved: boolean }>(`/pois/${id}/save`),
  unsave: (id: number) => api.del<{ poi_id: number; saved: boolean }>(`/pois/${id}/save`),
  dismiss: (id: number) => api.post<{ poi_id: number; dismissed: boolean }>(`/pois/${id}/dismiss`),
  interaction: (id: number, action: "view" | "click" | "show_similar" | "tell_me_more") =>
    api.post<void>(`/pois/${id}/interactions`, { action }),

  // plans
  createPlan: (spec: Partial<TripSpec>) => api.post<PlanOutcome>("/plans", spec as Record<string, unknown>),
  listPlans: () => api.get<{ plans: PlanListItem[] }>("/plans"),
  plan: (id: number, version?: number) => api.get<PlanView>(`/plans/${id}`, { version }),
  versions: (id: number) => api.get<{ versions: PlanVersion[] }>(`/plans/${id}/versions`),
  modify: (id: number, operations: Modification[], expected_version_no?: number) =>
    api.post<ModifyResponse>(`/plans/${id}/modify`, { operations, expected_version_no } as Record<string, unknown>),
  whatIf: (id: number, operations: Modification[]) =>
    api.post<ModifyResponse>(`/plans/${id}/what-if`, { operations } as Record<string, unknown>),
  applyVariant: (id: number, variantId: number) =>
    api.post<PlanView>(`/plans/${id}/variants/${variantId}/apply`),
  rejectVariant: (id: number, variantId: number) =>
    api.post<{ status: string }>(`/plans/${id}/variants/${variantId}/reject`),
  restore: (id: number, version: number) =>
    api.post<{ status: string; version_no: number }>(`/plans/${id}/restore/${version}`),
  savePlan: (id: number) => api.post<{ status: string }>(`/plans/${id}/save`),
  deletePlan: (id: number) => api.del<void>(`/plans/${id}`),

  // assistant & knowledge
  chat: (message: string, conversation_id?: string | null) =>
    api.post<AssistantResponse>("/assistant/chat", { message, conversation_id: conversation_id ?? undefined }),

  // auth & me
  register: (email: string, password: string, display_name?: string) =>
    api.post<TokenPair>("/auth/register", { email, password, display_name: display_name || undefined }, { anonymous: true }),
  login: (email: string, password: string, session_id: string) =>
    api.post<TokenPair>("/auth/login", { email, password, session_id }, { anonymous: true }),
  logout: (refresh_token: string) =>
    api.post<void>("/auth/logout", { refresh_token }, { anonymous: true }),
  me: () => api.get<User>("/me"),
  preferences: () => api.get<Preferences>("/me/preferences"),
  updatePreferences: (patch: Partial<Preferences>) =>
    api.put<Preferences>("/me/preferences", patch as Record<string, unknown>),
  saved: () => api.get<{ items: SavedItem[] }>("/me/saved"),
  deleteAccount: (password: string) => api.del<void>("/me", { password }),
};
