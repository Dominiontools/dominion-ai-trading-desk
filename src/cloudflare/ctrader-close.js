/** A successful close request is not proof that the broker is flat; reconcile broker state. */
export function findReconciledPosition(reconciled, positionId) {
  if (!reconciled || !Array.isArray(reconciled.positions)) {
    throw new Error("POSITION_CLOSE_RECONCILIATION_INVALID");
  }
  const matches = reconciled.positions.filter(
    (item) => String(item?.positionId ?? "") === String(positionId)
  );
  if (matches.length > 1) throw new Error("POSITION_CLOSE_RECONCILIATION_DUPLICATE_POSITION");
  return matches[0] ?? null;
}

export async function closeAndVerify(session, positionId, volume) {
  if (!/^\d{1,30}$/.test(String(positionId ?? "")) ||
      !(Number.isFinite(Number(volume)) && Number(volume) > 0)) {
    throw new Error("INVALID_POSITION_CLOSE_REQUEST");
  }
  let closeRequestError = null;
  try {
    await session.closePosition(Number(positionId), Number(volume));
  } catch (error) {
    closeRequestError = error instanceof Error ? error.name : "UnknownError";
  }
  const reconciled = await session.reconcile();
  const remaining = findReconciledPosition(reconciled, positionId);
  if (!remaining) return { closed: true, remainingVolume: 0, closeRequestError };
  const remainingVolume = Number(remaining.tradeData?.volume);
  if (!(Number.isFinite(remainingVolume) && remainingVolume > 0)) {
    throw new Error("POSITION_CLOSE_RECONCILIATION_VOLUME_INVALID");
  }
  return { closed: false, remaining, remainingVolume, closeRequestError };
}
