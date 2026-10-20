package com.railway.gateway.api.dto;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

@Schema(description = "Table from the generated document (section table or appendix)")
public record TaskContentTable(
        @Schema(description = "Caption, e.g. \"Приложение 3. Ведомость путей\"")
        String title,

        @Schema(description = "Column headers (may be empty)")
        List<String> headers,

        @Schema(description = "Table rows, cells as strings")
        List<List<String>> rows
) {
}
