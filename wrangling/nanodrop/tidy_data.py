"""Functions for handling data from the Deniz lab nanodrop, especially phase diagrams."""
# TODO: note nanodrop make and model
# TODO: automatically detect types instead of specifying? Skip type specification altogether and let everything be strings?

import re
import pandas as pd
import numpy as np
import warnings

import wrangling.utilities as utilities


def run_all(
    list_of_files, file_reader=pd.read_csv, file_reader_kwargs=dict(sep="\t"), **kwargs
):
    """
    Given a list of tsv file locations for nanodrop data, outputs a tidy pandas DataFrame.
    By default, drops measurements containing "buffer" or "blank" from the DataFrame.
    By default, "Sample ID" column is considered to have the form peptide_concentration_ratio,
        and columns will be created to contain this parsed info:
            "Peptide" (type: str), 
            "Peptide concentration (uM)" (type: float), 
            "RNA/Peptide Ratio" (type: float)
    
    Parameters
    ----------
    list_of_files : list 
        list of file locations given as strings
        expects tsv files by default
    file_reader : function
        function used to read files into dataframes
        default is pandas.read_csv
    file_reader_kwargs : dictionary
        kwargs to be passed to file_reader
        default is {sep="\t"} to read in tab-delimited .tsv files with pandas.read_csv
    **kwargs : kwargs to be passed to analyze_sample_names
    
    allowed kwargs : 
        ParseKey : an object of class ParseKey, default parse_rna_peptide
            Defines how to interpret "Sample ID"
            ParseKey options: parse_rna_peptide, parse_kdna_mg2, or provide your own
        drop_incorrectly_named_samples : bool, default False
            defines whether to drop rows whose "Sample ID" is unable to be parsed
        drop_buffers : bool, default True
            defines whether to drop rows containing "buffer" or "blank";
            if False, buffer rows all get Sample ID "blank"
    
    Returns
    -------
    a tidy pandas DataFrame

    Recommend producing list of files with code such as:
        import glob
        tsv_list = glob.glob('data_copy/*.tsv')    
    """

    df_list = [file_reader(file, **file_reader_kwargs) for file in list_of_files]

    for i, df in enumerate(df_list):
        df_list[i] = clean_up_columns(df_list[i])
        df_list[i] = rename_abs_columns_by_wavelength(df_list[i])

    try:
        for i, df in enumerate(df_list):
            pd.testing.assert_index_equal(df_list[0].columns, df.columns)
    except(AssertionError):
        warnings.warn("""\nColumn names do not match across all dataframes.
        Attempting to concatenate anyway. CHECK OUTPUT FOR ERRORS.""",
                     UserWarning)
    
    df = pd.concat(df_list, axis=0, ignore_index=True, sort=False
                  ).reset_index(drop=True)
    df = analyze_sample_names(df, **kwargs)
    df = utilities.break_out_date_and_time(df)

    return df


def clean_up_columns(df):
    """
    Remove garbage columns from a pandas DataFrame.
    
    Drops rows and columns with only NA contents.
    Tries to remove columns named "Unnamed", "User name", and "#";
        Passes quietly if these columns don't exist.
    """

    df = df.dropna(axis="columns", how="all").dropna(axis="rows", how="all")

    try:
        df = df.drop(axis=1, columns=df.columns[df.columns.str.contains("Unnamed")]
              ).drop(axis=1, columns=["User name", "#"])
    except KeyError:
        pass

    return df


def rename_abs_columns_by_wavelength(df):
    """
    Tidies absorbance values.
    
    Creates new columns "Abs {wavelength}" from wavelength values in previous "# (nm)" columns,
    and populates them with corresponding "# (Abs)" values as floats.
    
    Deletes "# (nm)" and "# (Abs)" columns.
    
    If passed an empty DataFrame, returns None
    """
    
    if len(df) == 0:
        return
    
    # re.escape allows literal treatment of the string; Python tries to treat it as regex otherwise
    nm_cols = df.columns[df.columns.str.contains(re.escape("(nm)"))]
    abs_col_names = []

    for i, current_row in df.iterrows():
        for nm_col in nm_cols:
            # ensure we're handling the corresponding Abs column 
            number = nm_col.split(" ")[0]
            abs_col = f"{number} (Abs)" 
            abs_col_names.append(abs_col)
        
            current_nm_value = int(current_row[nm_col])
            current_abs_value = current_row[abs_col]
        
            df.loc[i, f"Abs {current_nm_value}"] = current_abs_value

    # nm_cols and abs_col_names are different types requiring separate drops
    df = df.drop(axis=1, columns=nm_cols).drop(axis=1, columns=abs_col_names)
    
    return df


class ParseKey:
    """ParseKeys for use in _make_columns_by_parse_key and analyze_sample_names."""
    
    def __init__(self, *args, separator=None):
        """
        Initialize a ParseKey to interpret the "Sample ID" column of a DataFrame.
            
        *args : any number of two-tuples containing (column name, type) pairs
            these must be provided in the same order they appear in the "Sample ID" column
            all column names must be unique
        separator : str, default None
            distinguishes separate elements in the "Sample ID" column
            must be specified by kwarg; default is only allowed for a single arg arg
        
        For example:
            parse_rna_peptide = ParseKey(
                ("peptide", str),
                ("concentration", float),
                ("ratio", float),
                separator="_",)
            would be use to interpret a "Sample ID" column whose contents take the form
            peptide_concentration_ratio
        
        handle_input.request_parsekey_specifications() is a command-line utility that will assist in building a ParseKey.
        """
        
        if separator == None:
            try:
                assert len(args) == 1
            except AssertionError:
                raise RuntimeError("A separator must be specified by kwarg when more than one arg is given.")
        
        for arg in args:
            try:
                assert type(arg) == tuple
                assert len(arg) == 2
                assert type(arg[0]) == str
                assert type(arg[1]) == type
            except AssertionError:
                raise RuntimeError(f"\n{arg} is not a valid input."
                                   "Expected a tuple of length 2 where item 0 is a str and item 1 is a type.")
        
        self.separator = str(separator)
        self.parse_key = tuple([*args])
        
        column_names = []
        for key_pair in args:
            column_names.append(key_pair[0])
        self.column_names = tuple(column_names)
        
        try:
            assert len(column_names) == len(set(column_names))
        except AssertionError:
            raise RuntimeError("All column names must be unique.")


#provide some default ParseKey options
parse_rna_peptide = ParseKey(
    ("Peptide", str),
    ("Peptide concentration (uM)", float),
    ("RNA/Peptide Ratio", float),
    separator="_",
)

parse_kdna_mg2 = ParseKey(
    ("kDNA sample type", str),
    ("DNA concentration (ng/uL)", float),
    ("Mg2+ concentration", float),
    separator="_",
)


def analyze_sample_names(df, ParseKey=parse_rna_peptide, **kwargs):
    """
    Takes a dataframe and analyzes "Sample ID" column to produce new, tidy columns of data. 
    
    Parameters
    ----------
    df : a single dataframe with a "Sample ID" column whose contents are specified by the given ParseKey
    ParseKey : an object of class ParseKey defining how to interpret "Sample ID"
        ParseKey options: parse_rna_peptide, parse_kdna_mg2, or provide your own
    **kwargs : to be passed to _handle_incorrectly_named_samples
    
    Returns
    -------
    a tidy pandas DataFrame 
    new columns are defined by ParseKey and populated with parsed info from the Sample ID column.
    
    Troubleshooting
    ---------------
    Sample names may be considered incorrectly named due to:
        different number of items provided in ParseKey than found in "Sample ID" column
        incorrect number, arrangement, or type of separators
        failure to convert columns to type specified by ParseKey
            (ex, if a string is provided when a float is specified)
    """

    df = _make_columns_by_parse_key(df, ParseKey)

    incorrectly_named_samples = []
    for row_index, current_row in df.iterrows():
        try:
            split_sample_ID = current_row["Sample ID"].split(ParseKey.separator)

            if len(split_sample_ID) != len(ParseKey.parse_key) or "" in split_sample_ID:
                incorrectly_named_samples.append(row_index)
                # don't want to assign incorrectly formatted data
                continue

            for (key, datatype), sample_ID_data in zip(ParseKey.parse_key, split_sample_ID):
                # use df.loc to assign outside the for loop
                df.loc[row_index, key] = datatype(sample_ID_data)

        # type errors should be caught and recorded without stopping flow
        except (AttributeError, ValueError):
            incorrectly_named_samples.append(row_index)

    df = _handle_incorrectly_named_samples(df, incorrectly_named_samples, **kwargs)

    return df


def _make_columns_by_parse_key(df, ParseKey):
    """
    Adds new columns to a pandas DataFrame according to a given ParseKey object.
    Accepts types str, float, int, and bool.
    
    Parameters
    ----------
    df : a pandas DataFrame
    ParseKey : an object of class ParseKey defining how to interpret "Sample ID"
    """

    for key, datatype in ParseKey.parse_key:
        if datatype == str:
            df[key] = ""
        elif datatype in (float, int):
            df[key] = np.nan
        elif datatype == bool:
            df[key] = None
        else:
            warnings.warn(
                f"Unrecognized data type {datatype} in ParseKey.", UserWarning
            )

    return df


def _handle_incorrectly_named_samples(
    df,
    incorrectly_named_samples,
    drop_incorrectly_named_samples=False,
    drop_buffers=True,
):
    """
    Handles given incorrectly named samples in given DataFrame.
    
    If drop_buffers == True, buffer samples will be removed from df.
    If drop_buffers == False, buffer samples will be explicitly kept.
    If drop_inccorectly_named_samples == True, incorrectly named samples will be removed from df.
    If drop_inccorectly_named_samples == False, the user will be warned about any incorrectly named samples.
        If there are no incorrectly named samples, the function will pass quietly.
    
    Parameters
    ----------
    df : a pandas DataFrame
    incorrectly_named_samples = a list of indices
        specify incorrectly named samples in df
    drop_incorrectly_named_samples : bool, default False
        defines whether to drop rows whose "Sample ID" is unable to be parsed
    drop_buffers : bool, default True
        defines whether to drop rows containing "buffer" or "blank";
        if False, buffer rows all get Sample ID "blank"

    Warns
    -----
    UserWarning if any incorrectly named samples are kept.
    """

    blanks = _identify_buffer_measurements(df)
    df.loc[blanks, "Sample ID"] = "blank"
    incorrectly_named_samples = [index for index in incorrectly_named_samples 
                                 if index not in blanks]

    if drop_incorrectly_named_samples == False:
        if drop_buffers == True and len(blanks) > 0:
            df = df.drop(axis=0, index=blanks).reset_index(drop=True)
            print(f"Dropped {str(len(blanks))} buffer samples.")
            if len(incorrectly_named_samples) > 0:
                # if blanks are also dropped, the index is reset and is no longer accurate.
                warnings.warn(
                    f"\nSample names do not adhere to requirements in {len(incorrectly_named_samples)} rows."
                    + "\nIdentify incorrectly named samples by running analyze_sample_names on your DataFrame."
                    + "\nDrop incorrectly named samples by providing kwarg drop_incorrectly_named_samples=True.",
                    UserWarning,
                )

        elif len(incorrectly_named_samples) > 0:
            # this does not warn about any kept buffer samples
            warnings.warn(
                f"\nSample names do not adhere to requirements in the following rows: {incorrectly_named_samples}.",
                UserWarning,
            )

    elif drop_incorrectly_named_samples == True:
        if len(incorrectly_named_samples) > 0:
            df = df.drop(axis=0, index=incorrectly_named_samples).reset_index(drop=True)
            print(
                f"Dropped {str(len(incorrectly_named_samples))} incorrectly named samples."
            )

        if drop_buffers == True:
            # indices have changed since some were dropped; reassign blanks with new indices
            blanks = _identify_buffer_measurements(df)
            if len(blanks) > 0:
                df = df.drop(axis=0, index=blanks).reset_index(drop=True)
                print(f"Dropped {str(len(blanks))} buffer samples.")

    return df


def _identify_buffer_measurements(df):
    """
    Given a dataframe, identifies the rows where the 'Sample ID' column contains "buffer" or "blank."
    
    Returns a list of indices.
    """

    # first find variations on 'blank' and 'buffer' using boolean indexing
    buffers = df.loc[
        (df["Sample ID"].str.contains("lan")) | (df["Sample ID"].str.contains("uff"))
    ]

    return buffers.index


def break_out_date_and_time(df):
    """Moved to utilities."""
    
    warnings.warn("This function moved to utilities.py", DeprecationWarning)
    return utilities.break_out_date_and_time(df)


def drop_zeros(df, columns):
    """Moved to utilities."""
    
    warnings.warn("This function moved to utilities.py", DeprecationWarning)
    return utilities.drop_zeros(df, columns)


def find_outlier_bounds(df, col_to_check, ParseKey=None):
    """Moved to utilities.
    
    If ParseKey is given, passes ParseKey.column_names to groupby; otherwise, passes "Sample ID"
    """
    
    warnings.warn("This function moved to utilities.py", DeprecationWarning)
    
    if ParseKey == None:
        groupby = "Sample ID"
    else:
        groupby = list(ParseKey.column_names)
    
    return utilities.find_outlier_bounds(df, col_to_check, groupby=groupby)
    

def identify_outliers(df, col_to_check, **kwargs):
    """Moved to utilities.
    
    If groupby is given, passes it to utilities.identify_outliers.
    If ParseKey is given, passes ParseKey.column_names to groupby. 
    If neither is given, passes "Sample ID" to groupby.
    """
    
    if "groupby" not in kwargs.keys():
        try:
            kwargs["groupby"] = list(kwargs.pop("ParseKey").column_names)
        except: 
            kwargs["groupby"] = "Sample ID"
    
    warnings.warn("This function moved to utilities.py", DeprecationWarning)
    return utilities.identify_outliers(df, col_to_check, **kwargs)