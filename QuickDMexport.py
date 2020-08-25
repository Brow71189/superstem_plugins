# standard libraries
import gettext
import logging
import threading
import datetime
import os
import pathlib
import functools
import typing
import asyncio
import pkgutil
import json

# local libraries
from nion.swift import Panel
from nion.swift.model import ApplicationData
from nion.ui import Dialog, UserInterface
from nion.swift.model import ImportExportManager


_ = gettext.gettext


# utility functions
def divide_round_up(x, n):
    """ returns integer division rounded up """
    return int((x + (n - 1))/n)


# functions to handle prefix and postfix strings for renaming
def get_prefix_string(no_field_string):

    # pad No with leading zeros
    prefix_string = str(no_field_string.zfill(3)) + "_"
    return prefix_string


def get_postfix_string(sub_field_string, fov_field_string, descr_field_string):

    if str(sub_field_string) == "":
        postfix_string = ("_" + str(fov_field_string) + "nm_"
                              + str(descr_field_string))
    else:
        postfix_string = ("_" + str(sub_field_string) + "_"
                              + str(fov_field_string) + "nm_"
                              + str(descr_field_string))
    return postfix_string


def read_config_file(config_file: pathlib.Path):
    conf_file = config_file
    sstem_settings = {}
    logging.info("Reading SuperSTEM config file %s", conf_file)

    try:  # do nothing unless config file exists and is not empty
        if conf_file.is_file() and conf_file.stat().st_size != 0:
            with open(conf_file, "r") as f:
                sstem_settings = json.load(f)
                if sstem_settings == {}:
                    logging.info("WARNING - SuperSTEM config file %s empty", conf_file)
                    logging.info("        - Please edit and enter key/value pair for export_base_directory")
                else:
                    logging.info("- SuperSTEM settings are %s", sstem_settings)
        else:
            logging.info("WARNING - SuperSTEM config file %s NOT FOUND", conf_file)
            logging.info("        - Please create and enter key/value pair for export_base_directory")
    except Exception as e:
        logging.info("- Exception read_config_file %s", e)

    return sstem_settings


def get_sstem_settings(config_file):
    sstem_settings = read_config_file(config_file)
    return sstem_settings


def write_config_file(config_file: pathlib.Path, sstem_settings):
    conf_file = config_file

    try:
        if conf_file.is_file():
            with open(conf_file, "w") as f:
                logging.info("UPDATING SuperSTEM config file %s", conf_file)
                json.dump(sstem_settings, f, indent=4)
        else:
            logging.info("WARNING - SuperSTEM config file NOT FOUND")
    except Exception as e:
         logging.info("- Exception write_config_file %s", e)


class PanelQuickDMExportDelegate:
    """
    This panel plugin allows to set the persistent export directory from the
    session metadata and then to rename and export as DM file a display item
    based on four editable fields
    -
    Note: If you keep the Nionswift Library open overnight and then export the
    files, the default will be that the date of the export directory will not
    match the date of the Library. In this case one should manually change the
    date in the Export Dir field.
    ==========================================================================
    Revisions:

    20200825; DMH:
        added Initialise New Library button and minimal functionality
    20200821; DMH:
        added SuperSTEM's own JSON config file, reading/writing thereof
    20200818; DMH:
        adjusted style closer to pep8
        adding pop up warning dialog in case filename already exists
        fine-tuned button layout with stretching
    20200817; DMH:
        implementing pathlib for OS indepedent directory and file manipulations
        enabling & disabling export buttons based on re-editing editable fields
    20200811; DMH:
        initial version
    """

    def __init__(self, api):
        self.__api = api
        self.panel_id = "quickdmexport-panel"
        self.panel_name = _("Quick DM Export")
        self.panel_positions = ["left", "right"]
        self.panel_position = "right"
        self.api = api

        self.__action_dialog_open = False
        self.__library_dialog_open = False
        # initial edit status of editable fields
        self.have_no = False
        self.have_sub = False
        self.have_fov = False
        self.have_descr = False
        self.all_good = False
        # keep track of export buttons here
        self.button_widgets_list = []
        # get current datetime
        self.now = datetime.datetime.now()

        # we only export to DM
        self.io_handler_id = "dm-io-handler"
        self.writer = ImportExportManager.ImportExportManager().get_writer_by_id(self.io_handler_id)

        # SuperSTEM config file
        self.config_file = api.application.configuration_location / pathlib.Path("superstem_customisation.json")
        logging.info("Using %s for SuperSTEM customisations", self.config_file)
        #self.LibraryDialog = self.LibraryDialog.self
        #elf.sstem_settings = read_config_file(self.config_file)
        self.sstem_settings = get_sstem_settings(self.config_file)
        #self.expdir_base_string = get_sstem_settings(self.config_file).get('export_base_directory')
        self.expdir_base_string = self.sstem_settings.get('export_base_directory')


    def show_init_library_dialog(self):
        get_base_library_string_fn = self.get_base_library_string
        
        class InitLibraryDialog(Dialog.ActionDialog):

            def __init__(self, ui: UserInterface, *,
                         on_accept: typing.Optional[typing.Callable[[], None]]=None,
                         on_reject: typing.Optional[typing.Callable[[], None]]=None,
                         include_ok: bool=True,
                         include_cancel: bool=True,
                         window_style: typing.Optional[str]=None):
            #def __init__(self, ui, app):
                #super().__init__(ui, title=_("Initialise Library"), app=app, persistent_id="init_library_dialog")
                super().__init__(ui, window_style=window_style)
                
                # self.directory = self.ui.get_persistent_string("library_directory", self.ui.get_document_location())
                self.directory = get_base_library_string_fn()
                logging.info("library_base_string %s", self.directory)

                #DMH 200727
                library_base_name = datetime.datetime.now().strftime("%Y%m%d") + "_OPR_Snnn" + "_" +  _("NSL") 
                library_base_index = 0
                library_base_index_str = ""
                while os.path.exists(os.path.join(self.directory, library_base_name + library_base_index_str)):
                    library_base_index += 1
                    library_base_index_str = " " + str(library_base_index)

                self.library_name = library_base_name + library_base_index_str

                def handle_new():
                    self.library_name = self.__library_name_field.text
                    workspace_dir = os.path.join(self.directory, self.library_name)
                    Cache.db_make_directory_if_needed(workspace_dir)
                    path = os.path.join(workspace_dir, "Nion Swift Workspace.nslib")
                    if not os.path.exists(path):
                        with open(path, "w") as fp:
                            json.dump({}, fp)
                    if os.path.exists(path):
                        app.switch_library(workspace_dir)
                        return True
                    return False

                def handle_new_and_close():
                    handle_new()
                    self.request_close()
                    return False

                column = self.ui.create_column_widget()

                directory_header_row = self.ui.create_row_widget()
                directory_header_row.add_spacing(13)
                directory_header_row.add(self.ui.create_label_widget(_("Libraries Folder: "), properties={"font": "bold"}))
                directory_header_row.add_stretch()
                directory_header_row.add_spacing(13)

                show_directory_row = self.ui.create_row_widget()
                show_directory_row.add_spacing(26)
                directory_label = self.ui.create_label_widget(self.directory)
                show_directory_row.add(directory_label)
                show_directory_row.add_stretch()
                show_directory_row.add_spacing(13)

                choose_directory_row = self.ui.create_row_widget()
                choose_directory_row.add_spacing(26)
                choose_directory_button = self.ui.create_push_button_widget(_("Choose..."))
                choose_directory_row.add(choose_directory_button)
                choose_directory_row.add_stretch()
                choose_directory_row.add_spacing(13)

                library_name_header_row = self.ui.create_row_widget()
                library_name_header_row.add_spacing(13)
                library_name_header_row.add(self.ui.create_label_widget(_("Library Name: "), properties={"font": "bold"}))
                library_name_header_row.add_stretch()
                library_name_header_row.add_spacing(13)

                library_name_row = self.ui.create_row_widget()
                library_name_row.add_spacing(26)
                library_name_field = self.ui.create_line_edit_widget(properties={"width": 400})
                library_name_field.text = self.library_name
                library_name_field.on_return_pressed = handle_new_and_close
                library_name_field.on_escape_pressed = self.request_close
                library_name_row.add(library_name_field)
                library_name_row.add_stretch()
                library_name_row.add_spacing(13)

                column.add_spacing(12)
                column.add(directory_header_row)
                column.add_spacing(8)
                column.add(show_directory_row)
                column.add_spacing(8)
                column.add(choose_directory_row)
                column.add_spacing(16)
                column.add(library_name_header_row)
                column.add_spacing(8)
                column.add(library_name_row)
                column.add_stretch()
                column.add_spacing(16)

                def choose() -> None:
                    existing_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Library Directory"), self.directory)
                    if existing_directory:
                        self.directory = existing_directory
                        directory_label.text = self.directory
                        self.ui.set_persistent_string("library_directory", self.directory)

                choose_directory_button.on_clicked = choose

                self.add_button(_("Cancel"), lambda: True)
                self.add_button(_("Create Library"), handle_new)

                self.content.add(column)

                self.__library_name_field = library_name_field

            def show(self):
                super().show()
                self.__library_name_field.focused = True

        new_library_dialog = InitLibraryDialog(self.ui)
        new_library_dialog.show()

    def get_base_library_string(self):
        """ Reads the persistent export base directory from config file,
            falls back to /tmp/SSTEMData if it doesn't exist, and then
            constructs export directory path based on current year, date,
            microscopist, sampleID, sample description (i.e. sample_area).
            Returns the export directory path as string.
        """
        # site based base directory for exports as configurd in SuperSTEM config file
        logging.info("Called get_base_library_string")
        self.base_dir_string = get_sstem_settings(self.config_file).get('export_base_directory')            
    
        # fall back to /tmp/SSTEMData/<year> or C:\tmp\SSTEMData\<year>
        if self.base_dir_string is None:
            base_dir_path = pathlib.Path('/tmp/SSTEMData/')
        else:
            base_dir_path = pathlib.Path(self.base_dir_string)
        base_date_string = "_".join([str(self.now.year),
                                       str(self.now.month),
                                       str(self.now.day)])
        base_session_string = "_".join([
            str(self.__api.library.get_library_value("stem.session.microscopist")), 
            str(self.__api.library.get_library_value("stem.session.sample")),
            str(self.__api.library.get_library_value("stem.session.sample_area"))
        ])
        # pathlib "/" method to ;contruct export dir path:
        base_library_path = base_dir_path.joinpath(
                str(self.now.year),
                base_date_string + "_" + base_session_string)
        #logging.info(" expdir_path %s", expdir_path)
        return str(base_library_path)
        
    def show_library_dialog(self, title_string, have_ok=True, have_cancel=True):

        # this puts the get_base_library_string in the scope of the class LibraryDialog:      
        get_base_library_string_fn = self.get_base_library_string
    
        class LibraryDialog(Dialog.ActionDialog):
            """
            Create a modeless dialog that always stays on top of the UI 
            by default (can be controlled with the parameter 'window_style').

            Parameters:
            -----------
            ui : An instance of nion.ui.UserInterface, required.
            on_accept : callable, optional.
                This method will be called when the user clicks 'OK'
            on_reject : callable, optional.
                This method will be called when the user clicks 'Cancel' or the 'X'-button
            include_ok : bool, optional
                Whether to include the 'OK' button.
            include_cancel : bool, optional
                Whether to include the 'Cancel' button.
            window_style : str, optional
                Pass in 'dialog' here if you want the Dialog to move into the background when clicking outside
                of it. The default value 'tool' will cause it to always stay on top of Swift.
            """
            def __init__(self, ui: UserInterface, *,
                         on_accept: typing.Optional[typing.Callable[[], None]]=None,
                         on_reject: typing.Optional[typing.Callable[[], None]]=None,
                         include_ok: bool=have_ok,
                         include_cancel: bool=have_cancel,
                         window_style: typing.Optional[str]=None):

                super().__init__(ui, window_style=window_style)
                logging.info("Calling LibraryDialog")
                self.on_accept = on_accept
                self.on_reject = on_reject
                self.directory = get_base_library_string_fn()
                logging.info("library_base_string %s", self.directory)

                library_base_name = datetime.datetime.now().strftime("%Y%m%d") + "_OPR_Snnn" + "_" +  _("NSL") 
                library_base_index = 0
                library_base_index_str = ""
                while os.path.exists(os.path.join(self.directory, library_base_name + library_base_index_str)):
                    library_base_index += 1
                    library_base_index_str = " " + str(library_base_index)

                self.library_name = library_base_name + library_base_index_str
                
                def handle_new():
                    self.library_name = self.__library_name_field.text
                    workspace_dir = os.path.join(self.directory, self.library_name)
                    Cache.db_make_directory_if_needed(workspace_dir)
                    path = os.path.join(workspace_dir, "Nion Swift Workspace.nslib")
                    if not os.path.exists(path):
                        with open(path, "w") as fp:
                            json.dump({}, fp)
                    if os.path.exists(path):
                        app.switch_library(workspace_dir)
                        return True
                    return False

                def handle_new_and_close():
                    handle_new()
                    self.request_close()
                    return False
                
                column = self.ui.create_column_widget()
                row = self.ui.create_row_widget()
                label = self.ui.create_label_widget(title_string)

                directory_header_row = self.ui.create_row_widget()
                directory_header_row.add_spacing(13)
                directory_header_row.add(self.ui.create_label_widget(_("Libraries Folder: "), properties={"font": "bold"}))
                directory_header_row.add_stretch()
                directory_header_row.add_spacing(13)

                show_directory_row = self.ui.create_row_widget()
                show_directory_row.add_spacing(26)
                directory_label = self.ui.create_label_widget(self.directory)
                show_directory_row.add(directory_label)
                show_directory_row.add_stretch()
                show_directory_row.add_spacing(13)

                choose_directory_row = self.ui.create_row_widget()
                choose_directory_row.add_spacing(26)
                choose_directory_button = self.ui.create_push_button_widget(_("Choose..."))
                choose_directory_row.add(choose_directory_button)
                choose_directory_row.add_stretch()
                choose_directory_row.add_spacing(13)

                library_name_header_row = self.ui.create_row_widget()
                library_name_header_row.add_spacing(13)
                library_name_header_row.add(self.ui.create_label_widget(_("Library Name: "), properties={"font": "bold"}))
                library_name_header_row.add_stretch()
                library_name_header_row.add_spacing(13)

                library_name_row = self.ui.create_row_widget()
                library_name_row.add_spacing(26)
                library_name_field = self.ui.create_line_edit_widget(properties={"width": 400})
                library_name_field.text = self.library_name
                library_name_field.on_return_pressed = handle_new_and_close
                library_name_field.on_escape_pressed = self.request_close
                library_name_row.add(library_name_field)
                library_name_row.add_stretch()
                library_name_row.add_spacing(13)

                row.add_spacing(10)
                row.add(label)
                row.add_spacing(10)
                row.add_stretch()

                column.add_spacing(12)
                column.add(directory_header_row)
                column.add_spacing(8)
                column.add(show_directory_row)
                column.add_spacing(8)
                column.add(choose_directory_row)
                column.add_spacing(16)
                column.add(library_name_header_row)
                column.add_spacing(8)
                column.add(library_name_row)
                column.add_stretch()
                column.add_spacing(16)
                
                column.add_spacing(10)
                column.add(row)
                column.add_spacing(10)
                column.add_stretch()

                def choose() -> None:
                    existing_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Library Directory"), self.directory)
                    if existing_directory:
                        self.directory = existing_directory
                        directory_label.text = self.directory
                        self.ui.set_persistent_string("library_directory", self.directory)

                choose_directory_button.on_clicked = choose

                def on_cancel_clicked():
                    if self.on_reject:
                        self.on_reject()
                    # Return 'True' to tell Swift to close the Dialog
                    return True
                if include_cancel:
                    self.add_button('Cancel', on_cancel_clicked)

                def on_ok_clicked():
                    if self.on_accept:
                        self.on_accept()
                    # Return 'True' to tell Swift to close the Dialog
                    return True
                if include_ok:
                    self.add_button('OK', on_ok_clicked)
                    
                self.add_button(_("Cancel"), lambda: True)  # short way to create cancel button and action
                self.add_button(_("Create Library"), handle_new)

                self.content.add(column)

                self.__library_name_field = library_name_field
                

            def about_to_close(self, geometry: str, state: str) -> None:
                """
                Required to properly close the Dialog.
                """
                if self.on_reject:
                    self.on_reject()
                super().about_to_close(geometry, state)

        # We track open dialogs to ensure that only one dialog can be open at a time
        if not self.__library_dialog_open:
            self.__library_dialog_open = True
            dc = self.__api.application.document_controllers[0]._document_controller
            # This function will inform the main panel that the dialog has been closed, so that it will allow
            # opening a new one
            def report_dialog_closed():
                self.__library_dialog_open = False
            # We pass in `report_dialog_closed` so that it gets called when the dialog is closed.
            # If you want to invoke different actions when the user clicks 'OK' and 'Canclel', you can of course pass
            # in two different functions for `on_accept` and `on_reject`.
            LibraryDialog(dc.ui, on_accept=report_dialog_closed, on_reject=report_dialog_closed).show()


    def show_action_dialog(self, title_string, have_ok=True, have_cancel=True):
        class WarningDialog(Dialog.ActionDialog):
            """
            Create a modeless dialog that always stays on top of the UI 
            by default (can be controlled with the parameter 'window_style').

            Parameters:
            -----------
            ui : An instance of nion.ui.UserInterface, required.
            on_accept : callable, optional.
                This method will be called when the user clicks 'OK'
            on_reject : callable, optional.
                This method will be called when the user clicks 'Cancel' or the 'X'-button
            include_ok : bool, optional
                Whether to include the 'OK' button.
            include_cancel : bool, optional
                Whether to include the 'Cancel' button.
            window_style : str, optional
                Pass in 'dialog' here if you want the Dialog to move into the background when clicking outside
                of it. The default value 'tool' will cause it to always stay on top of Swift.
            """
            def __init__(self, ui: UserInterface, *,
                         on_accept: typing.Optional[typing.Callable[[], None]]=None,
                         on_reject: typing.Optional[typing.Callable[[], None]]=None,
                         include_ok: bool=have_ok,
                         include_cancel: bool=have_cancel,
                         window_style: typing.Optional[str]=None):

                super().__init__(ui, window_style=window_style)

                self.on_accept = on_accept
                self.on_reject = on_reject

                def on_ok_clicked():
                    if self.on_accept:
                        self.on_accept()
                    # Return 'True' to tell Swift to close the Dialog
                    return True
                if include_ok:
                    self.add_button('OK', on_ok_clicked)

                def on_cancel_clicked():
                    if self.on_reject:
                        self.on_reject()
                    # Return 'True' to tell Swift to close the Dialog
                    return True
                if include_cancel:
                    self.add_button('Cancel', on_cancel_clicked)

                column = self.ui.create_column_widget()
                row = self.ui.create_row_widget()
                label = self.ui.create_label_widget(title_string)

                row.add_spacing(10)
                row.add(label)
                row.add_spacing(10)
                row.add_stretch()

                column.add_spacing(10)
                column.add(row)
                column.add_spacing(10)
                column.add_stretch()

                self.content.add(column)

            def about_to_close(self, geometry: str, state: str) -> None:
                """
                Required to properly close the Dialog.
                """
                if self.on_reject:
                    self.on_reject()
                super().about_to_close(geometry, state)

        # We track open dialogs to ensure that only one dialog can be open at a time
        if not self.__action_dialog_open:
            self.__action_dialog_open = True
            dc = self.__api.application.document_controllers[0]._document_controller
            # This function will inform the main panel that the dialog has been closed, so that it will allow
            # opening a new one
            def report_dialog_closed():
                self.__action_dialog_open = False
            # We pass in `report_dialog_closed` so that it gets called when the dialog is closed.
            # If you want to invoke different actions when the user clicks 'OK' and 'Canclel', you can of course pass
            # in two different functions for `on_accept` and `on_reject`.
            WarningDialog(dc.ui, on_accept=report_dialog_closed, on_reject=report_dialog_closed).show()

    def create_panel_widget(self, ui, document_controller):
        self.ui = ui
        self.document_controller = document_controller

        # list of export buttons (will be ordered in rows of 4 buttons)
        button_list = [
                "HAADF", "MAADF", "BF", "ABF",
                "LAADF", "SI-Survey", "SI-During", "SI-After",
                "SI-EELS", "EELS-sngl", "Ronchi"
                ]
        no_buttons = 4
        # initialise export dir field with empty string
        self.expdir_string = ""

        # function to construct the export directory string
        def get_export_dir_string():
            """ Reads the persistent export base directory from config file,
                falls back to /tmp/SSTEMData if it doesn't exist, and then
                constructs export directory path based on current year, date,
                microscopist, sampleID, sample description (i.e. sample_area).
                Returns the export directory path as string.
            """
            # site based base directory for exports as configurd in SuperSTEM config file
            self.expdir_base_string = get_sstem_settings(self.config_file).get('export_base_directory')            

            # fall back to /tmp/SSTEMData/<year> or C:\tmp\SSTEMData\<year>
            if self.expdir_base_string is None:
                expdir_base_path = pathlib.Path('/tmp/SSTEMData/')
            else:
                expdir_base_path = pathlib.Path(self.expdir_base_string)
            expdir_date_string = "_".join([str(self.now.year),
                                           str(self.now.month),
                                           str(self.now.day)])
            expdir_session_string = "_".join([
                str(self.__api.library.get_library_value("stem.session.microscopist")), 
                str(self.__api.library.get_library_value("stem.session.sample")),
                str(self.__api.library.get_library_value("stem.session.sample_area"))
            ])
            # pathlib "/" method to ;contruct export dir path:
            expdir_path = expdir_base_path.joinpath(
                    str(self.now.year),
                    expdir_date_string + "_" + expdir_session_string)
            #logging.info(" expdir_path %s", expdir_path)
            return str(expdir_path)

        def write_persistent_vars(self):
            """ Writes export base directory path, export directory path and
                chosen export format to config files (superstem and Nion persistent data).
            """
            write_config_file(self.config_file, self.sstem_settings)
            self.__api.application.document_controllers[0]._document_controller.ui.set_persistent_string('export_directory', self.expdir_string)                                                
            self.__api.application.document_controllers[0]._document_controller.ui.set_persistent_string('export_filter', 'DigitalMicrograph Files files (*.dm3 *.dm4)')

        # === create main column widget
        column = ui.create_column_widget()
        
        # == create initialise new library button row
        new_library_button_row = ui.create_row_widget()
        self.new_library_button = ui.create_push_button_widget(_("Initialise New Library"))
        new_library_button_row.add(self.new_library_button)
        def new_library_button_clicked():
            #self.show_init_library_dialog()
            self.show_library_dialog("New Library", True, True)
            #init_library_dialog = InitLibraryDialog(self.ui, self)
            #init_library_dialog.show()
        self.new_library_button.on_clicked = new_library_button_clicked

        # == create update export dir button row widget
        update_expdir_row = ui.create_row_widget()
        # create button
        self.update_expdir_button = ui.create_push_button_widget(
                _("Set Exp Dir from Session Metadata"))
        # add button to row
        update_expdir_row.add(self.update_expdir_button)

        def update_expdir_button_clicked():
            """ Writes updated export directory string from session meta data
                to persistent data and ensures export as DM file.
                Gets fired when expdir_button is clicked.
            """
            expdir_string = get_export_dir_string()
            self.expdir_field_edit.text = expdir_string
            self.__api.application.document_controllers[0]._document_controller.ui.set_persistent_string('export_directory', expdir_string)
            self.__api.application.document_controllers[0]._document_controller.ui.set_persistent_string('export_filter', 'DigitalMicrograph Files files (*.dm3 *.dm4)')
        # define listening slot
        self.update_expdir_button.on_clicked = update_expdir_button_clicked
        update_expdir_row.add_spacing(15)
        update_expdir_row.add_stretch  # hmm, not stretching!?
        # add label to row
        update_expdir_row.add(ui.create_label_widget(_("Export Dir:")))
        update_expdir_row.add_spacing(2)
        #update_expdir_row.add_stretch

        # == create editable export dir field row widget
        expdir_row = ui.create_row_widget()
        self.expdir_field_edit = ui.create_line_edit_widget()

        def handle_expdir_field_changed(text):
            """ Handles manual edits to the expdir
            """
            self.expdir_string = text
            write_persistent_vars(self)
            self.expdir_field_edit.request_refocus()  # not sure what this does
        self.expdir_field_edit.on_editing_finished = handle_expdir_field_changed
        self.expdir_field_edit.text = self.expdir_string
        expdir_row.add(self.expdir_field_edit)
        expdir_row.add_spacing(2)
        update_expdir_row.add_stretch

        # == create label row widget
        label_row = ui.create_row_widget()
        # define labels
        # properties parameters are not accepted here !?:
        # edit_row.add(ui.create_label_widget("dummy", properties={"width":100}))
        label_row.add(ui.create_label_widget(_("No")))
        label_row.add_spacing(1)
        label_row.add(ui.create_label_widget(_(" Sub")))
        label_row.add_spacing(1)
        label_row.add(ui.create_label_widget(_(" FOV")))
        label_row.add_spacing(1)
        label_row.add(ui.create_label_widget(_(" Description")))
        label_row.add_spacing(2)

        # == create editable fields row widget
        fields_row = ui.create_row_widget()
        # define editable fields for field row
        self.fields_no_edit = ui.create_line_edit_widget()
        self.fields_sub_edit = ui.create_line_edit_widget()
        self.fields_fov_edit = ui.create_line_edit_widget()
        self.fields_descr_edit = ui.create_line_edit_widget()

        def handle_no_changed(text):
            """ calls the update button state function for each export button
                and passes the current text in the No field
            """
            for button in self.button_widgets_list:
                self.update_button_state(button, no=text)
            # fields_nr_sub.request_refocus()

        def handle_sub_changed(text):
            for button in self.button_widgets_list:
                self.update_button_state(button, sub=text)
            # fields_fov_edit.request_refocus()

        def handle_fov_changed(text):
            for button in self.button_widgets_list:
                self.update_button_state(button, fov=text)
            # fields_descr_edit.request_refocus()

        def handle_descr_changed(text):
            for button in self.button_widgets_list:
                self.update_button_state(button, descr=text)
            # fields_descr_edit.request_refocus()

        # what happens when editing in field is done (= mouse click s.w. else)
        self.fields_no_edit.on_editing_finished = handle_no_changed
        self.fields_sub_edit.on_editing_finished = handle_sub_changed
        self.fields_fov_edit.on_editing_finished = handle_fov_changed
        self.fields_descr_edit.on_editing_finished = handle_descr_changed
        # add each field to fields row widget
        fields_row.add(self.fields_no_edit)
        fields_row.add_spacing(1)
        fields_row.add(self.fields_sub_edit)
        fields_row.add_spacing(1)
        fields_row.add(self.fields_fov_edit)
        fields_row.add_spacing(1)
        fields_row.add(self.fields_descr_edit)
        fields_row.add_spacing(2)
        #fields_row.add_stretch()

        # == create export button rows (contained in a column widget)
        self.button_column = ui.create_column_widget()
        # add button rows with 4 buttons each, taking buttons from button_list
        # line_no counts up to how many rows are required
        for line_no in range(divide_round_up(len(button_list), no_buttons)):
            button_row = self.create_button_line(line_no, button_list,
                                                 no_buttons)
            self.button_column.add(button_row)

        # == add the row widgets to the column widget
        column.add_spacing(8)
        column.add(new_library_button_row)
        column.add(update_expdir_row)
        column.add_spacing(3)
        column.add(expdir_row)
        column.add_spacing(8)
        column.add(label_row)
        column.add(fields_row)
        column.add_spacing(8)
        column.add(self.button_column)
        column.add_spacing(5)
        column.add_stretch()

        # default state of export buttons:
        for button in self.button_widgets_list:
            button._widget.enabled = False

        return column

    def update_button_state(self, button, **kwargs):
        """ This gets called for each editable field. It updates the relevant
            status boolean based on text in the field, and then the overall
            status boolean. Then enables/disables export button widget
            depending on the overall status boolean.
            -----------
            Parameters: button = the current export button widget
                        kwargs = the name and text value of the editable field
        """
        # update current status of each editable field
        if 'no' in kwargs and kwargs['no'] != "":
            self.have_no = True
        elif 'no' in kwargs and kwargs['no'] == "":
            self.have_no = False
        if 'sub' in kwargs and kwargs['sub'] != "":
            self.have_sub = True
        elif 'sub' in kwargs and kwargs['sub'] == "":
            self.have_sub = False
        if 'fov' in kwargs and kwargs['fov'] != "":
            self.have_fov = True
        elif 'fov' in kwargs and kwargs['fov'] == "":
            self.have_fov = False
        if 'descr' in kwargs and kwargs['descr'] != "":
            self.have_descr = True
        elif 'descr' in kwargs and kwargs['descr'] == "":
            self.have_descr = False

        # only if related status booleans of required fields
        # (No, FOV and Description) are all True can we set all good to go
        if self.have_no and self.have_fov and self.have_descr:
            self.all_good = True
        else:
            self.all_good = False

        def update():
            """ enables/disables button widget
            """
            if self.all_good:
                button._widget.enabled = True
            else:
                button._widget.enabled = False

        self.__api.queue_task(update)

    def create_button_line(self, index, button_list, no_buttons):
        """ Creates a row of up to 4 buttons inside a column.
            -----------
            Parameters: index = current line_no of export button rows
                        button_list = list of strings with button names
        """
        # === create main column in which the rows goes
        column = self.ui.create_column_widget()
        row = self.ui.create_row_widget()

        def export_button_clicked(button_list_index):
            """ Renames selected DISPLAY item and saves as DM to the selected
                export directory.
                Note, all export buttons are disabled until all required fields
                (No, FOV, descripton) are filled in.
                -----------
                Parameters: button_list_index = selected export button string
            """
            # !!! find out whether by passing "ui" to the function we can
            # replace the loooong __api.application.... string with "ui"
            writer = self.writer
            prefix = get_prefix_string(self.fields_no_edit.text)
            postfix = get_postfix_string(self.fields_sub_edit.text,
                                         self.fields_fov_edit.text,
                                         self.fields_descr_edit.text)
            item = self.__api.application.document_controllers[0]._document_controller.selected_display_item
            item.title = (prefix + str(button_list[button_list_index])
                          + postfix)
            directory_string = self.__api.application.document_controllers[0]._document_controller.ui.get_persistent_string('export_directory')
            logging.info("Exporting to %s ", directory_string)
            filename = "{0}.{1}".format(item.title, writer.extensions[0])
            export_path = pathlib.Path(directory_string).joinpath(filename)

            if not pathlib.Path.is_dir(export_path.parent):
                export_path.parent.mkdir(parents=True)  # mkdir -p
            else:
                logging.info("- Export Directory already exists")

                if not pathlib.Path.is_file(export_path):
                    ImportExportManager.ImportExportManager().write_display_item_with_writer(self.__api.application.document_controllers[0]._document_controller.ui, writer, item, str(export_path))
                    logging.info("- %s", export_path.name)
                else:
                    # launch popup dialog if filename already exists
                    logging.info("- Could not export - file exists")
                    self.show_action_dialog("Could not export - file exists", True, False)

        # == make buttons
        # don't know how many buttons there are, so it's possible to have
        # not enough to fill a row of 4
        try:
            self.button1 = self.ui.create_push_button_widget(_(str(button_list[no_buttons*index])))
            row.add(self.button1)
            row.add_spacing(1)
            self.button_widgets_list.append(self.button1)
            self.button1.on_clicked = functools.partial(export_button_clicked, (no_buttons*index))     
        except IndexError:
            # logging.info("export_button_clicked: IndexError at Button1, row %s", index)
            pass
        try:
            self.button2 = self.ui.create_push_button_widget(_(str(button_list[(no_buttons*index)+1])))
            row.add(self.button2)
            row.add_spacing(1)
            self.button_widgets_list.append(self.button2)
            self.button2.on_clicked = functools.partial(export_button_clicked, (no_buttons*index)+1)     
        except IndexError:
            # logging.info("export_button_clicked: IndexError at  Button2, row %s", index)
            pass
        try:
            self.button3 = self.ui.create_push_button_widget(_(str(button_list[(no_buttons*index)+2])))
            row.add(self.button3)
            row.add_spacing(1)
            self.button_widgets_list.append(self.button3)
            self.button3.on_clicked = functools.partial(export_button_clicked, (no_buttons*index)+2)        
        except IndexError:
            # logging.info("export_button_clicked: IndexError at Button3, row %s", index)
            pass
        try:
            self.button4 = self.ui.create_push_button_widget(_(str(button_list[(no_buttons*index)+3])))
            row.add(self.button4)
            row.add_spacing(2)
            self.button_widgets_list.append(self.button4)
            self.button4.on_clicked = functools.partial(export_button_clicked, (no_buttons*index)+3)          
        except IndexError:
            # logging.info("export_button_clicked: IndexError at Button4, row %s ", index)
            pass
        #row.add_stretch()

        column.add(row)
        column.add_spacing(0)

        return column


class PanelQuickDMExportExtension(object):

    # required for Swift to recognize this as an extension class.
    extension_id = "nion.swift.examples.quickdmexport_panel"

    def __init__(self, api_broker):
        # grab the api object.
        api = api_broker.get_api(version="1", ui_version="1")
        # be sure to keep a reference or it will be closed immediately.
        self.__panel_ref = api.create_panel(PanelQuickDMExportDelegate(api))

    def close(self):
        # close will be called when the extension is unloaded. in turn, close any references so they get closed. this
        # is not strictly necessary since the references will be deleted naturally when this object is deleted.
        self.__panel_ref.close()
        self.__panel_ref = None
