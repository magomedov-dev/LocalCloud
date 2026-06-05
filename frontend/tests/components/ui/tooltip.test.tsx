import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

describe("Tooltip", () => {
  it("отображает содержимое в открытом состоянии", () => {
    render(
      <TooltipProvider>
        <Tooltip open>
          <TooltipTrigger>Наведи</TooltipTrigger>
          <TooltipContent>Подсказка</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    expect(screen.getByText("Наведи")).toBeInTheDocument();
    // Radix дублирует содержимое (видимое + для скринридеров).
    expect(screen.getAllByText("Подсказка").length).toBeGreaterThan(0);
  });

  it("скрывает содержимое в закрытом состоянии", () => {
    render(
      <TooltipProvider>
        <Tooltip open={false}>
          <TooltipTrigger>Наведи</TooltipTrigger>
          <TooltipContent>Подсказка</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    expect(screen.queryByText("Подсказка")).not.toBeInTheDocument();
  });

  it("применяет className к содержимому", () => {
    render(
      <TooltipProvider>
        <Tooltip open>
          <TooltipTrigger>t</TooltipTrigger>
          <TooltipContent className="extra-tip">Текст</TooltipContent>
        </Tooltip>
      </TooltipProvider>,
    );
    const tip = document.querySelector(".extra-tip");
    expect(tip).not.toBeNull();
    expect(tip).toHaveClass("rounded-md");
  });
});
