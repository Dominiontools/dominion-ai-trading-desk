/**
 * Submit a cTrader demo close and confirm the broker's resulting position state.
 * A successful close request is not proof that the position is flat. If the
 * close response is lost, reconcile before deciding whether another close is
 * needed; the broker's position state is authoritative.
 */
export async function closeAndVerify(session, positionId, volume) {
  if (!Number.isSafeInteger(Number(positionId)) || Number(positionId) <= 0 ||
      !(Number.isFinite(Number(volume)) && Number(volume) > 0)) {
    throw new Error("INVALID_POSITION_CLOSE_REQUEST");
  }

  let closeRequestError = null;
  try {
    await session.closePosition(Number(positionId), Number(volume));
  } catch (error) {
    // A timeout or transport error does not prove the broker rejected the close.
    closeRequestError = error instanceof Error ? error.name : "UnknownError";
  }

  const reconciled = await session.reconcile();
  if (!reconciled || !Array.isArray(reconciled.positions)) {
    throw new Error("POSITION_CLOSE_RECONCILIATION_INVALID");
  }

  const remaining = reconciled.positions.find(
    (item) => Number(item?.positionId) === Number(positionId),
  );
  if (!remaining) {
    return { closed: true, remainingVolume: 0, closeRequestError };
  }

  const tradeData = remaining.tradeData;
  const remainingVolume = Number(tradeData?.volume);
  if (!(Number.isFinite(remainingVolume) && remainingVolume > 0)) {
    throw new Error("POSITION_CLOSE_RECONCILIATION_VOLUME_INVALID");
  }
  return { closed: false, remaining, remainingVolume, closeRequestError };
}
