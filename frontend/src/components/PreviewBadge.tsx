import { FlaskConical } from "lucide-react";

/** Marks anything that is a stand-in until its real backend exists. */
export default function PreviewBadge({ reason }: { reason: string }) {
  return (
    <span className="preview-badge" title={reason}>
      <FlaskConical size={13} aria-hidden="true" /> Preview
    </span>
  );
}
