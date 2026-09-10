import { AtivoDetalheView } from "@/components/AtivoDetalheView";

export default async function AtivoDetalhePage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  return <AtivoDetalheView ticker={ticker} />;
}
