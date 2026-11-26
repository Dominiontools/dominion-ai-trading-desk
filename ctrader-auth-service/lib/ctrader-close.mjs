/**
 * Submit a cTrader demo close and confirm the broker's resulting position state.
 * A successful close request is not proof that the position is flat.
 */
export async function closeAndVerify(session, positionId, volume) {
  if (!Number.isSafeInteger(Number(positionId)) || Number(positionId) <= 0 ||
      !(Number.isFinite(Number(volume)) && Number(volume) > 0)) {
    throw new Error("INVALID_POSITION_CLOSE_REQUEST");
  }

  await session.closePosition(Number(positionId), Number(volume));
  const reconciled = await session.reconcile();
  if (!reconciled || !Array.isArray(reconciled.positions)) {
    throw new Error("POSITION_CLOSE_RECONCILIATION_INVALID");
  }

  const remaining = reconciled.positions.find(
    (item) => Number(item?.positionId) === Number(positionId),
  );
  if (!remaining) return { closed: true, remainingVolume: 0 };

  const tradeData = remaining.tradeData;
  const remainingVolume = Number(tradeData?.volume);
  if (!(Number.isFinite(remainingVolume) && remainingVolume > 0)) {
    throw new Error("POSITION_CLOSE_RECONCILIATION_VOLUME_INVALID");
  }
  return { closed: false, remaining, remainingVolume };
}
