/** Query keys and data hooks. Server state lives in TanStack Query only. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { endpoints, type PoiQuery, type RecommendArgs } from "@/lib/api/endpoints";
import type { Modification, PoiCard } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";

export const qk = {
  context: ["context"] as const,
  categories: ["categories"] as const,
  collections: (ids?: string[]) => ["collections", ids ?? "default"] as const,
  recommend: (args: RecommendArgs) => ["recommend", args] as const,
  pois: (q: PoiQuery) => ["pois", q] as const,
  poi: (id: number | string) => ["poi", String(id)] as const,
  similar: (id: number) => ["similar", id] as const,
  saved: ["saved"] as const,
  preferences: ["preferences"] as const,
  plans: ["plans"] as const,
  plan: (id: number, version?: number) => ["plan", id, version ?? "current"] as const,
  versions: (id: number) => ["versions", id] as const,
};

export function useHomeContext() {
  return useQuery({ queryKey: qk.context, queryFn: endpoints.context, staleTime: 5 * 60_000 });
}

export function useCategories() {
  return useQuery({ queryKey: qk.categories, queryFn: endpoints.categories, staleTime: Infinity });
}

export function useCollections(ids?: string[]) {
  return useQuery({
    queryKey: qk.collections(ids),
    queryFn: () => endpoints.collections(ids, 8),
    staleTime: 10 * 60_000,
  });
}

export function useRecommend(args: RecommendArgs, enabled = true) {
  return useQuery({
    queryKey: qk.recommend(args),
    queryFn: () => endpoints.recommend(args),
    enabled,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

export function usePois(q: PoiQuery, enabled = true) {
  return useQuery({
    queryKey: qk.pois(q),
    queryFn: ({ signal }) => endpoints.pois(q, signal),
    enabled,
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
  });
}

export function usePoi(id: number | string) {
  return useQuery({ queryKey: qk.poi(id), queryFn: () => endpoints.poi(id), staleTime: 10 * 60_000 });
}

export function useSimilar(id: number | undefined) {
  return useQuery({
    queryKey: qk.similar(id ?? 0),
    queryFn: () => endpoints.similar(id as number, 6),
    enabled: Boolean(id),
    staleTime: 10 * 60_000,
  });
}

export function useSaved() {
  const { isAuthenticated } = useAuth();
  return useQuery({ queryKey: qk.saved, queryFn: endpoints.saved, enabled: isAuthenticated });
}

export function useSavedIds(): Set<number> {
  const saved = useSaved();
  return useMemo(() => new Set((saved.data?.items ?? []).map((i) => i.id)), [saved.data]);
}

/** Save / unsave with an optimistic update. Returns null when signed out. */
export function useToggleSave() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ poi, save }: { poi: PoiCard; save: boolean }) =>
      save ? endpoints.save(poi.id) : endpoints.unsave(poi.id),
    onMutate: async ({ poi, save }) => {
      await qc.cancelQueries({ queryKey: qk.saved });
      const prev = qc.getQueryData<{ items: PoiCard[] }>(qk.saved);
      qc.setQueryData<{ items: PoiCard[] }>(qk.saved, (old) => {
        const items = old?.items ?? [];
        return { items: save ? [poi, ...items.filter((i) => i.id !== poi.id)] : items.filter((i) => i.id !== poi.id) };
      });
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(qk.saved, ctx.prev);
      toast.error("Couldn't update your saved places. Try again.");
    },
    onSuccess: (_d, { poi, save }) => {
      toast.success(save ? `Saved ${poi.name}` : `Removed ${poi.name} from saved`);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: qk.saved }),
  });
}

export function usePreferences() {
  const { isAuthenticated } = useAuth();
  return useQuery({ queryKey: qk.preferences, queryFn: endpoints.preferences, enabled: isAuthenticated });
}

// Plans belong to the signed-in user or to this browser session, so they wait
// until a stored session has been restored — otherwise the first request after
// a reload goes out anonymously and comes back empty.
export function usePlans() {
  const { ready } = useAuth();
  return useQuery({ queryKey: qk.plans, queryFn: endpoints.listPlans, staleTime: 30_000, enabled: ready });
}

export function usePlan(id: number, version?: number) {
  const { ready } = useAuth();
  return useQuery({
    queryKey: qk.plan(id, version),
    queryFn: () => endpoints.plan(id, version),
    enabled: ready,
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
}

export function useVersions(id: number) {
  const { ready } = useAuth();
  return useQuery({ queryKey: qk.versions(id), queryFn: () => endpoints.versions(id), enabled: ready });
}

export function useModifyPlan(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ops, expected }: { ops: Modification[]; expected?: number }) =>
      endpoints.modify(id, ops, expected),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plan", id] });
      void qc.invalidateQueries({ queryKey: qk.versions(id) });
      void qc.invalidateQueries({ queryKey: qk.plans });
    },
  });
}

export function useWhatIf(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ops: Modification[]) => endpoints.whatIf(id, ops),
    onSuccess: () => void qc.invalidateQueries({ queryKey: qk.versions(id) }),
  });
}

export function errorMessage(err: unknown, fallback = "Something went wrong. Please try again."): string {
  if (err instanceof ApiError) return err.message || fallback;
  return fallback;
}
