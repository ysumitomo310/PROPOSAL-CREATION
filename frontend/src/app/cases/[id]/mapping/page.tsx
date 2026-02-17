export default async function MappingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold">マッピング結果</h1>
      <p className="mt-4 text-gray-500">案件ID: {id}</p>
      <p className="mt-2 text-gray-500">
        TASK-E03: マッピング結果一覧テーブル
      </p>
    </div>
  );
}
