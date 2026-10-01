export interface ReviewDraft {
  reviewId: string;
  text: string;
  savedText: string;
  savedRevision: number;
  conflict: boolean;
}

export function newReviewDraft(reviewId: string, savedText: string, savedRevision: number): ReviewDraft {
  return { reviewId, text: savedText, savedText, savedRevision, conflict: false };
}

// A refresh may acknowledge our save or bring someone else's correction.
// Preserve local edits until the operator explicitly reloads the saved version.
export function reconcileReviewDraft(draft: ReviewDraft, reviewId: string, savedText: string, savedRevision: number): ReviewDraft {
  if (draft.reviewId !== reviewId || draft.text === draft.savedText || draft.text === savedText) {
    return newReviewDraft(reviewId, savedText, savedRevision);
  }
  if (draft.savedText === savedText && draft.savedRevision === savedRevision) return draft;
  return { ...draft, savedText, savedRevision, conflict: true };
}

export function editReviewDraft(draft: ReviewDraft, text: string): ReviewDraft {
  return { ...draft, text, conflict: draft.conflict && text !== draft.savedText };
}
