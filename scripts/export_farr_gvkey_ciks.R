#!/usr/bin/env Rscript

usage <- function() {
  cat(
    paste(
      "Usage: Rscript scripts/export_farr_gvkey_ciks.R [options]",
      "",
      "Export farr::gvkey_ciks to a CSV accepted by",
      "scripts/prepare_gvkey_cik_crosswalk.py.",
      "",
      "Options:",
      "  --out PATH              Output CSV path.",
      "                          Default: DATA_DIR/external/farr_gvkey_ciks_raw.csv",
      "  --as-of-year YEAR       End year for open-ended links.",
      "                          Default: current calendar year",
      "  --source-version TEXT   Override source_version column.",
      "                          Default: farr <installed-version>",
      "  --install-missing       Install farr from CRAN if it is not installed.",
      "  --repos URL             CRAN repo for --install-missing.",
      "                          Default: https://cloud.r-project.org",
      "  --help                  Show this message.",
      sep = "\n"
    )
  )
}

parse_args <- function(args) {
  data_dir <- Sys.getenv("DATA_DIR", unset = "")
  opts <- list(
    out = "",
    as_of_year = as.integer(format(Sys.Date(), "%Y")),
    source_version = "",
    install_missing = FALSE,
    repos = "https://cloud.r-project.org"
  )

  i <- 1
  while (i <= length(args)) {
    arg <- args[[i]]
    if (arg == "--help" || arg == "-h") {
      usage()
      quit(status = 0)
    } else if (arg == "--install-missing") {
      opts$install_missing <- TRUE
      i <- i + 1
    } else if (arg %in% c("--out", "--as-of-year", "--source-version", "--repos")) {
      if (i == length(args)) {
        stop(sprintf("%s requires a value", arg), call. = FALSE)
      }
      value <- args[[i + 1]]
      if (arg == "--out") {
        opts$out <- value
      } else if (arg == "--as-of-year") {
        opts$as_of_year <- as.integer(value)
      } else if (arg == "--source-version") {
        opts$source_version <- value
      } else if (arg == "--repos") {
        opts$repos <- value
      }
      i <- i + 2
    } else {
      stop(sprintf("Unknown option: %s", arg), call. = FALSE)
    }
  }

  if (!nzchar(opts$out)) {
    if (!nzchar(data_dir)) {
      stop("DATA_DIR is required when --out is not provided", call. = FALSE)
    }
    opts$out <- file.path(data_dir, "external", "farr_gvkey_ciks_raw.csv")
  }
  if (is.na(opts$as_of_year) || opts$as_of_year < 1800 || opts$as_of_year > 2200) {
    stop("--as-of-year must be a four-digit year", call. = FALSE)
  }
  opts
}

coerce_date <- function(x) {
  if (inherits(x, "Date")) {
    return(x)
  }
  if (inherits(x, "POSIXt")) {
    return(as.Date(x))
  }
  if (is.numeric(x)) {
    return(as.Date(x, origin = "1970-01-01"))
  }
  as.Date(as.character(x))
}

normalize_text <- function(x) {
  out <- as.character(x)
  out[out %in% c("NA", "NaN", "NULL", "Inf", "-Inf")] <- NA_character_
  out
}

opts <- parse_args(commandArgs(trailingOnly = TRUE))

if (!requireNamespace("farr", quietly = TRUE)) {
  if (isTRUE(opts$install_missing)) {
    install.packages("farr", repos = opts$repos)
  } else {
    stop(
      paste(
        "The R package 'farr' is not installed.",
        "Run install.packages('farr') or pass --install-missing."
      ),
      call. = FALSE
    )
  }
}

data("gvkey_ciks", package = "farr", envir = environment())
links <- get("gvkey_ciks")

required <- c("gvkey", "cik", "first_date", "last_date")
missing <- setdiff(required, names(links))
if (length(missing) > 0) {
  stop(
    sprintf("farr::gvkey_ciks is missing required columns: %s", paste(missing, collapse = ", ")),
    call. = FALSE
  )
}

first_date <- coerce_date(links$first_date)
last_date <- coerce_date(links$last_date)
start_year <- as.integer(format(first_date, "%Y"))
end_year <- as.integer(format(last_date, "%Y"))
end_year[is.na(end_year)] <- opts$as_of_year

source_version <- opts$source_version
if (!nzchar(source_version)) {
  source_version <- paste0("farr ", as.character(utils::packageVersion("farr")))
}
extracted_at <- format(as.POSIXct(Sys.time(), tz = "UTC"), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
iid <- if ("iid" %in% names(links)) normalize_text(links$iid) else NA_character_

out <- data.frame(
  gvkey = normalize_text(links$gvkey),
  issuer_cik = normalize_text(links$cik),
  start_year = start_year,
  end_year = end_year,
  iid = iid,
  first_date = as.character(first_date),
  last_date = as.character(last_date),
  source = "farr_gvkey_ciks",
  source_version = source_version,
  extracted_at = extracted_at,
  match_method = "farr_gvkey_ciks_date_range",
  match_score = NA_real_,
  stringsAsFactors = FALSE
)

keep <- !is.na(out$gvkey) &
  !is.na(out$issuer_cik) &
  !is.na(out$start_year) &
  !is.na(out$end_year) &
  out$end_year >= out$start_year
out <- unique(out[keep, , drop = FALSE])
out <- out[order(out$gvkey, out$start_year, out$issuer_cik, out$iid), , drop = FALSE]

dir.create(dirname(opts$out), recursive = TRUE, showWarnings = FALSE)
write.csv(out, opts$out, row.names = FALSE, na = "")

cat(
  sprintf(
    "Wrote %d farr GVKEY-CIK date-range rows to %s\n",
    nrow(out),
    opts$out
  )
)
cat(sprintf("Source version: %s\n", source_version))
