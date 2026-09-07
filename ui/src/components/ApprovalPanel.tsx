import { useState } from "react";
import type { RcaProposal } from "@/types";

interface Props {
  rcaProposal: RcaProposal;
  onDecide: (action: "approve" | "reject", note: string) => Promise<void>;
}

export function ApprovalPanel({ rcaProposal, onDecide }: Props) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const decide = async (action: "approve" | "reject") => {
    setBusy(true);
    try {
      await onDecide(action, note);
      setNote("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="approval-box">
      <strong>⏸ Đang chờ HITL — RCA cần con người duyệt</strong>
      <p className="muted">
        Hypothesis: {rcaProposal.hypothesis ?? "(không có)"} — confidence: {rcaProposal.confidence ?? "?"}
        {" "}
        <em>(chỉ tham khảo — mọi RCA đều bắt buộc duyệt, không có ngưỡng nào để bỏ qua bước này)</em>
      </p>

      <label htmlFor="approvalNote">Ghi chú</label>
      <textarea
        id="approvalNote"
        placeholder="Lý do approve/reject..."
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />

      <div className="row">
        <button className="ok" disabled={busy} onClick={() => void decide("approve")}>
          ✅ Approve
        </button>
        <button className="danger" disabled={busy} onClick={() => void decide("reject")}>
          ❌ Reject
        </button>
      </div>
    </div>
  );
}
