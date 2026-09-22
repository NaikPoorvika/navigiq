/**
 * Profile and preferences. These are the same preferences the recommendation
 * engine reads ("For you", and the planner's defaults) — nothing here is
 * cosmetic.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Check, LogOut, Trash } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageFooter } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/overlay";
import { Chip, EmptyState, ErrorState, Field, Input, SectionHeader, Segmented, Skeleton } from "@/components/ui/primitives";
import { endpoints } from "@/lib/api/endpoints";
import type { Preferences } from "@/lib/api/types";
import { useAuth } from "@/lib/auth";
import { EXPLORE_CATEGORIES, MOODS, categoryMeta } from "@/lib/categories";
import { useDocumentTitle } from "@/lib/hooks";
import { errorMessage, qk, usePreferences } from "@/lib/queries";

const DIETS = [
  { key: "vegetarian", label: "Vegetarian" },
  { key: "pure_vegetarian", label: "Pure vegetarian" },
  { key: "vegan", label: "Vegan" },
  { key: "halal", label: "Halal" },
  { key: "jain", label: "Jain" },
];

const PACES = [
  { value: "quick" as const, label: "Quick" },
  { value: "balanced" as const, label: "Balanced" },
  { value: "relaxed" as const, label: "Relaxed" },
];

const EMPTY: Preferences = {
  favorite_categories: [], disliked_categories: [], favorite_moods: [], preferred_pace: null,
  typical_budget_inr: null, indoor_outdoor_preference: null, dietary_preferences: [], favorite_areas: [],
};

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

export function ProfilePage() {
  useDocumentTitle("Profile");
  const { user, isAuthenticated, signOut } = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const prefs = usePreferences();
  const [draft, setDraft] = useState<Preferences>(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [budget, setBudget] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (prefs.data) {
      setDraft(prefs.data);
      setBudget(prefs.data.typical_budget_inr ? String(prefs.data.typical_budget_inr) : "");
      setDirty(false);
    }
  }, [prefs.data]);

  const save = useMutation({
    // Only the fields the API accepts: the GET also returns read-only ones.
    mutationFn: (p: Preferences) => endpoints.updatePreferences({
      favorite_categories: p.favorite_categories,
      disliked_categories: p.disliked_categories,
      favorite_moods: p.favorite_moods,
      preferred_pace: p.preferred_pace,
      typical_budget_inr: p.typical_budget_inr,
      indoor_outdoor_preference: p.indoor_outdoor_preference,
      dietary_preferences: p.dietary_preferences,
      favorite_areas: p.favorite_areas,
    }),
    onSuccess: (p) => {
      qc.setQueryData(qk.preferences, p);
      void qc.invalidateQueries({ queryKey: ["recommend"] });
      void qc.invalidateQueries({ queryKey: ["collections"] });
      setDirty(false);
      toast.success("Preferences saved — recommendations will use them");
    },
    onError: (e) => toast.error(errorMessage(e, "Couldn't save your preferences.")),
  });

  const removeAccount = useMutation({
    mutationFn: () => endpoints.deleteAccount(password),
    onSuccess: async () => {
      await signOut();
      toast("Your account and its data are deleted.");
      void navigate({ to: "/" });
    },
    onError: (e) => toast.error(errorMessage(e, "Couldn't delete the account.")),
  });

  const update = (patch: Partial<Preferences>) => {
    setDraft((d) => ({ ...d, ...patch }));
    setDirty(true);
  };

  if (!isAuthenticated || !user) {
    return (
      <>
        <main id="main" className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
          <EmptyState
            title="Sign in to set your preferences"
            description="Preferences shape what NavigIQ recommends and how it plans by default."
            action={<><Button asChild><Link to="/signin">Sign in</Link></Button><Button asChild variant="secondary"><Link to="/signup">Create account</Link></Button></>}
          />
        </main>
        <PageFooter />
      </>
    );
  }

  return (
    <>
      <main id="main" className="mx-auto max-w-3xl px-4 pb-24 pt-6 sm:px-6">
        <SectionHeader title="Profile" description={user.email} />

        {prefs.isPending ? (
          <div className="space-y-4">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32" />)}</div>
        ) : prefs.isError ? (
          <ErrorState description="Your preferences didn't load." onRetry={() => void prefs.refetch()} />
        ) : (
          <div className="space-y-8">
            <section>
              <h2 className="font-display text-lg font-semibold">What you like</h2>
              <p className="mt-1 text-sm text-muted-foreground">Used to rank “For you” and to fill in a plan when you don't say.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {EXPLORE_CATEGORIES.map((c) => (
                  <Chip key={c} className="h-9" selected={draft.favorite_categories.includes(c)}
                    onClick={() => update({ favorite_categories: toggle(draft.favorite_categories, c) })}>
                    {categoryMeta(c).label}
                  </Chip>
                ))}
              </div>
            </section>

            <section>
              <h2 className="font-display text-lg font-semibold">Moods you go for</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {MOODS.map((m) => (
                  <Chip key={m.key} className="h-9" selected={draft.favorite_moods.includes(m.key)}
                    onClick={() => update({ favorite_moods: toggle(draft.favorite_moods, m.key) })}>
                    {m.label}
                  </Chip>
                ))}
              </div>
            </section>

            <section>
              <h2 className="font-display text-lg font-semibold">Rather avoid</h2>
              <div className="mt-3 flex flex-wrap gap-2">
                {EXPLORE_CATEGORIES.map((c) => (
                  <Chip key={c} className="h-9" selected={draft.disliked_categories.includes(c)}
                    onClick={() => update({ disliked_categories: toggle(draft.disliked_categories, c) })}>
                    {categoryMeta(c).label}
                  </Chip>
                ))}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Avoided kinds are filtered out of recommendations and plans.</p>
            </section>

            <section className="grid gap-5 sm:grid-cols-2">
              <div>
                <h2 className="font-display text-lg font-semibold">Pace</h2>
                <Segmented className="mt-3" label="Preferred pace" value={draft.preferred_pace ?? "balanced"}
                  onChange={(v) => update({ preferred_pace: v })} options={PACES} />
              </div>
              <div>
                <h2 className="font-display text-lg font-semibold">Indoor or outdoor</h2>
                <Segmented className="mt-3" label="Indoor or outdoor" value={draft.indoor_outdoor_preference ?? "any"}
                  onChange={(v) => update({ indoor_outdoor_preference: v === "any" ? null : v })}
                  options={[{ value: "any" as const, label: "Either" }, { value: "indoor" as const, label: "Indoor" }, { value: "outdoor" as const, label: "Outdoor" }]} />
              </div>
            </section>

            <section className="grid gap-5 sm:grid-cols-2">
              <Field id="budget" label="Typical budget per outing" hint="Rupees for the whole party. Used when you don't give one.">
                <Input id="budget" inputMode="numeric" value={budget} placeholder="e.g. 1500"
                  onChange={(e) => {
                    const v = e.target.value.replace(/[^\d]/g, "").slice(0, 6);
                    setBudget(v);
                    update({ typical_budget_inr: v ? Number(v) : null });
                  }} />
              </Field>
              <div>
                <h2 className="font-display text-lg font-semibold">Food</h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  {DIETS.map((d) => (
                    <Chip key={d.key} className="h-9" selected={draft.dietary_preferences.includes(d.key)}
                      onClick={() => update({ dietary_preferences: toggle(draft.dietary_preferences, d.key) })}>
                      {d.label}
                    </Chip>
                  ))}
                </div>
              </div>
            </section>

            <div className="sticky bottom-24 z-20 flex items-center gap-3 rounded-2xl bg-card/95 p-3 shadow-lift ring-1 ring-border backdrop-blur md:bottom-4">
              <Button onClick={() => save.mutate(draft)} loading={save.isPending} disabled={!dirty}>
                <Check aria-hidden="true" /> Save preferences
              </Button>
              {dirty ? <p className="text-sm text-muted-foreground">Unsaved changes</p> : <p className="text-sm text-muted-foreground">Everything's saved</p>}
            </div>

          </div>
        )}

        <section className="mt-10 border-t border-border pt-6">
          <h2 className="font-display text-lg font-semibold">Account</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => void signOut().then(() => navigate({ to: "/" }))}>
              <LogOut aria-hidden="true" /> Sign out
            </Button>
            <Button variant="ghost" className="text-danger hover:bg-danger-soft" onClick={() => setConfirmDelete(true)}>
              <Trash aria-hidden="true" /> Delete account
            </Button>
          </div>
        </section>
      </main>
      <PageFooter />

      <Dialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete your account?"
        description="Your plans, saved places and preferences are deleted with it. This can't be undone."
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" disabled={!password} loading={removeAccount.isPending} onClick={() => removeAccount.mutate()}>
              Delete everything
            </Button>
          </div>
        }
      >
        <Field id="confirm-password" label="Confirm with your password">
          <Input id="confirm-password" type="password" value={password} autoComplete="current-password" onChange={(e) => setPassword(e.target.value)} />
        </Field>
      </Dialog>
    </>
  );
}
